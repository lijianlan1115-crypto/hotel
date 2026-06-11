from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import statistics
from contextlib import closing

from runtime.adapters.beyondh import beyondh_call, build_beyondh_request
from runtime.adapters.database import database_source_enabled, database_template_result
from runtime.common import emit, now_local, redacted_request, today
from runtime.contracts import standard_envelope
from runtime.decisions.calendar import get_calendar_day
from runtime.decisions.demand import sample_snapshot
from runtime.safety.approvals import approval_gate
from runtime.safety.auth import build_auth_context, permission_gate
from runtime.safety.guards import price_guard
from runtime.storage import approval_get, connect, log_api


def _to_float(value, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_discount_factors(value) -> list[float]:
    if value in (None, ""):
        return [1.0]
    if isinstance(value, (int, float)):
        parsed = [float(value)]
    elif isinstance(value, (list, tuple)):
        parsed = [_to_float(item, 0) for item in value]
    else:
        parsed = [_to_float(item.strip(), 0) for item in str(value).split(",")]
    factors = [factor for factor in parsed if factor > 0]
    return factors or [1.0]


def _activity_discount_factor(factors: list[float]) -> float:
    product = 1.0
    for factor in factors:
        product *= factor
    return round(product, 4)


def _build_ota_price_model(ota_base_price, activity_discount_factors=None, pms_price=None) -> dict:
    base_price = round(_to_float(ota_base_price), 2)
    factors = _parse_discount_factors(activity_discount_factors)
    combined_factor = _activity_discount_factor(factors)
    pms_reference = None if pms_price in (None, "") else round(_to_float(pms_price), 2)
    return {
        "price_target_type": "ota_backend_base_price",
        "ota_base_price": base_price,
        "ota_activity_discount_factors": factors,
        "ota_activity_discount_factor": combined_factor,
        "ota_estimated_final_price": round(base_price * combined_factor, 2),
        "pms_price_reference_only": pms_reference,
        "pms_price_used_for_execution": False,
        "model_note": "S5/S6 调整的是 OTA 后台门市价；外网预估价由后台价乘活动折扣得到；PMS 价仅作营收参考。",
    }


def _select_price_candidate(prices_result: dict) -> dict | None:
    if prices_result.get("status") != "ok":
        return None
    snapshots = ((prices_result.get("payload") or {}).get("price_snapshots") or [])
    if not snapshots:
        return None
    return max(snapshots, key=lambda item: _to_float(item.get("room_fee")) or _to_float(item.get("current_price")))


def _result_is_fresh(result: dict) -> bool:
    if result.get("status") != "ok":
        return False
    payload = result.get("payload") or {}
    return payload.get("freshness_status") == "fresh"


def _payload(result: dict) -> dict:
    return result.get("payload") or {}


def _business_date(args: argparse.Namespace) -> str:
    return str(getattr(args, "date", None) or getattr(args, "begin_date", None) or today())[:10]


def _date_part(value) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text[:10] if len(text) >= 10 else None


def _round_to_five(value: float) -> int:
    return int(round(value / 5.0) * 5)


def _clamp(value: float, floor: float | None, ceiling: float | None) -> float:
    if floor is not None:
        value = max(value, floor)
    if ceiling is not None:
        value = min(value, ceiling)
    return value


def _price_bounds_by_room_type(price_payload: dict) -> dict[str, dict]:
    bounds: dict[str, dict] = {}
    for item in price_payload.get("price_snapshots") or []:
        room_type = str(item.get("room_type_id") or item.get("room_type_name") or "").strip()
        if not room_type:
            continue
        bounds[room_type] = {
            "room_type_id": room_type,
            "room_type_name": item.get("room_type_name") or room_type,
            "floor_price": item.get("price_floor"),
            "ceiling_price": item.get("price_ceiling") or item.get("listed_price"),
            "current_price": item.get("current_price"),
            "price_guard_source": "price_snapshot",
        }
    return bounds


def _date_type_factor(db_path: str, target_date: str) -> tuple[float, str]:
    try:
        day = get_calendar_day(db_path, target_date)
    except Exception:
        return 1.0, "default"
    if day.get("is_adjusted_workday"):
        return 0.95, "adjusted_workday"
    if day.get("is_holiday"):
        return 1.15, "holiday"
    if day.get("is_weekend"):
        return 1.08, "weekend"
    return 1.0, "normal_day"


def _order_basis_date(order: dict) -> str | None:
    return _date_part(order.get("business_date")) or _date_part(order.get("checkin_time"))


def _order_room_type(order: dict) -> str:
    return str(order.get("room_type_id") or order.get("room_type_name") or "unknown").strip() or "unknown"


def _effective_order_price(order: dict) -> float | None:
    detail = order.get("price_detail") or {}
    for key in ("daily_price", "room_fee", "rack_rate"):
        value = _to_float(detail.get(key), 0)
        if value > 0:
            if key == "room_fee":
                nights = _to_float(order.get("room_nights"), 0) or 1
                return value / nights
            return value
    return None


def expected_occupancy_result(args: argparse.Namespace) -> dict:
    business_date = _business_date(args)
    if not database_source_enabled():
        return {
            "status": "data_gap",
            "hotel_id": args.hotel_id,
            "data_business_date": business_date,
            "expected_occupancy_status": "missing_database_source",
            "pricing_blocked_reason": "expected_occupancy_requires_reservation_and_stayover_data",
            "freshness_status": "missing_date",
            "today_label_allowed": False,
        }

    operating = database_template_result("operating_snapshot", args.hotel_id, date=business_date)
    reservations = database_template_result("reservation_snapshot", args.hotel_id, date=business_date)
    stayovers = database_template_result("stayover_snapshot", args.hotel_id, date=business_date)
    operating_payload = _payload(operating)
    reservation_payload = _payload(reservations)
    stayover_payload = _payload(stayovers)
    missing = []
    for label, result in (("operating_snapshot", operating), ("reservation_snapshot", reservations), ("stayover_snapshot", stayovers)):
        if result.get("status") != "ok":
            missing.append(label)
    freshness = {
        "operating_snapshot": operating_payload.get("freshness_status"),
        "reservation_snapshot": reservation_payload.get("freshness_status"),
        "stayover_snapshot": stayover_payload.get("freshness_status"),
    }
    source_diagnostics = {
        "reservation_snapshot": {
            "source_status": reservation_payload.get("source_status"),
            "raw_row_count": reservation_payload.get("raw_row_count"),
            "filtered_room_count": reservation_payload.get("filtered_room_count"),
            "status_filter_aliases": reservation_payload.get("status_filter_aliases"),
        },
        "stayover_snapshot": {
            "source_status": stayover_payload.get("source_status"),
            "raw_row_count": stayover_payload.get("raw_row_count"),
            "filtered_room_count": stayover_payload.get("filtered_room_count"),
            "status_filter_aliases": stayover_payload.get("status_filter_aliases"),
        },
    }
    source_issues = []
    for label, diagnostic in source_diagnostics.items():
        if diagnostic.get("source_status") in {"no_rows", "status_filtered_zero"}:
            source_issues.append(f"{label}:{diagnostic['source_status']}")

    total_rooms = int(_to_float(operating_payload.get("total_rooms"), 0))
    stayover_rooms = int(_to_float(stayover_payload.get("stayover_rooms"), 0))
    new_arrival_rooms = int(_to_float(reservation_payload.get("new_arrival_rooms"), 0))
    unavailable_rooms = int(
        _to_float(
            operating_payload.get("unavailable_rooms_tonight"),
            _to_float(operating_payload.get("maintenance_rooms"), 0) + _to_float(operating_payload.get("dirty_rooms"), 0),
        )
    )
    if total_rooms <= 0:
        missing.append("total_rooms")
    if missing or source_issues:
        return {
            "status": "data_gap",
            "hotel_id": args.hotel_id,
            "data_business_date": business_date,
            "expected_occupancy_status": "source_diagnostic_failed" if source_issues else "missing_required_sources",
            "pricing_blocked_reason": "expected_occupancy_requires_reservation_and_stayover_data",
            "missing_sources": sorted(set(missing + source_issues)),
            "field_freshness": freshness,
            "source_diagnostics": source_diagnostics,
            "database_evidence": {
                "operating_snapshot": operating,
                "reservation_snapshot": reservations,
                "stayover_snapshot": stayovers,
            },
            "freshness_status": "missing_date",
            "today_label_allowed": False,
        }

    sellable_rooms = max(total_rooms - unavailable_rooms, 1)
    expected_sold = max(stayover_rooms + new_arrival_rooms, 0)
    occupancy = round(min(expected_sold / sellable_rooms, 1.0), 4)
    all_fresh = all(value == "fresh" for value in freshness.values())
    status = "ok" if all_fresh else "historical_only"
    return {
        "status": status,
        "hotel_id": args.hotel_id,
        "data_business_date": business_date,
        "data_snapshot_time": operating_payload.get("data_snapshot_time"),
        "freshness_status": "fresh" if all_fresh else "stale",
        "business_status": "current" if all_fresh else "demo_or_historical",
        "today_label_allowed": bool(all_fresh),
        "expected_occupancy_status": "confirmed" if all_fresh else "historical_simulation",
        "stayover_rooms": stayover_rooms,
        "new_arrival_rooms": new_arrival_rooms,
        "unavailable_rooms_tonight": unavailable_rooms,
        "sellable_rooms_tonight": sellable_rooms,
        "expected_sold_rooms_tonight": expected_sold,
        "expected_occupancy_tonight": occupancy,
        "occupancy_basis": (
            f"续住 {stayover_rooms} 间 + 今日预订 {new_arrival_rooms} 间；"
            f"可售房 {sellable_rooms} 间，总房量 {total_rooms} 间，不可售 {unavailable_rooms} 间。"
        ),
        "field_freshness": freshness,
        "source_diagnostics": source_diagnostics,
    }


def baseline_price_result(args: argparse.Namespace) -> dict:
    business_date = _business_date(args)
    if not database_source_enabled():
        return {
            "status": "data_gap",
            "hotel_id": args.hotel_id,
            "business_date": business_date,
            "baseline_price_method": "seven_day_room_type_median_x_date_type_factor_v1",
            "pricing_blocked_reason": "baseline_price_requires_order_and_price_history",
            "freshness_status": "missing_date",
        }
    orders_result = database_template_result("order_snapshot", args.hotel_id, date=business_date)
    prices_result = database_template_result("price_snapshot", args.hotel_id, date=business_date)
    orders_payload = _payload(orders_result)
    prices_payload = _payload(prices_result)
    if prices_result.get("status") == "ok" and prices_payload.get("price_snapshot_source") == "business_dataset_v1.price_data":
        factor, factor_label = _date_type_factor(getattr(args, "db", ":memory:"), business_date)
        rows = []
        for item in prices_payload.get("price_snapshots") or []:
            room_type = str(item.get("room_type_id") or item.get("room_type_name") or "").strip()
            if not room_type:
                continue
            base = _to_float(item.get("normal_price"), _to_float(item.get("current_price"), 0))
            if base <= 0:
                continue
            floor = None if item.get("price_floor") in (None, "") else _to_float(item.get("price_floor"))
            ceiling = None if item.get("price_ceiling") in (None, "") else _to_float(item.get("price_ceiling"))
            raw = base * factor
            rounded = _round_to_five(raw)
            rows.append(
                {
                    "room_type_id": room_type,
                    "room_type_name": item.get("room_type_name") or room_type,
                    "raw_baseline_price": round(raw, 2),
                    "rounded_baseline_price": rounded,
                    "final_baseline_price": _clamp(float(rounded), floor, ceiling),
                    "baseline_basis_days": 1,
                    "basis_price_count": 1,
                    "date_type_factor": factor,
                    "date_type_factor_label": factor_label,
                    "price_floor": floor,
                    "price_ceiling": ceiling,
                    "current_price": item.get("current_price"),
                    "competitor_price": item.get("competitor_price"),
                    "price_guard_source": "price_data",
                }
            )
        if rows:
            fresh_prices = prices_payload.get("freshness_status") == "fresh"
            return {
                "status": "ok" if fresh_prices else "historical_only",
                "hotel_id": args.hotel_id,
                "business_date": business_date,
                "data_business_date": prices_payload.get("data_business_date") or business_date,
                "data_snapshot_time": prices_payload.get("data_snapshot_time"),
                "freshness_status": prices_payload.get("freshness_status") or "missing_date",
                "baseline_price_method": "business_dataset_v1_price_data_x_date_type_factor_v1",
                "baseline_price_by_room_type": rows,
                "date_type_factor": factor,
                "date_type_factor_label": factor_label,
                "pricing_blocked_reason": None if fresh_prices else "price_data_not_fresh",
                "database_evidence": {"price_snapshot": prices_result},
            }
    if orders_result.get("status") != "ok" or prices_result.get("status") != "ok":
        return {
            "status": "data_gap",
            "hotel_id": args.hotel_id,
            "business_date": business_date,
            "baseline_price_method": "seven_day_room_type_median_x_date_type_factor_v1",
            "pricing_blocked_reason": "baseline_price_requires_order_and_price_history",
            "database_evidence": {"order_snapshot": orders_result, "price_snapshot": prices_result},
            "freshness_status": "missing_date",
        }

    target = dt.date.fromisoformat(business_date)
    start = target - dt.timedelta(days=7)
    prices_by_room: dict[str, list[float]] = {}
    basis_dates_by_room: dict[str, set[str]] = {}
    names: dict[str, str] = {}
    for order in orders_payload.get("orders") or []:
        basis = _order_basis_date(order)
        if not basis:
            continue
        try:
            basis_date = dt.date.fromisoformat(basis)
        except ValueError:
            continue
        if not (start <= basis_date < target):
            continue
        price = _effective_order_price(order)
        if price is None or price <= 0:
            continue
        room_type = _order_room_type(order)
        prices_by_room.setdefault(room_type, []).append(price)
        basis_dates_by_room.setdefault(room_type, set()).add(basis)
        names[room_type] = order.get("room_type_name") or room_type

    factor, factor_label = _date_type_factor(getattr(args, "db", ":memory:"), business_date)
    bounds_by_room = _price_bounds_by_room_type(prices_payload)
    rows = []
    for room_type, values in sorted(prices_by_room.items()):
        median_price = float(statistics.median(values))
        raw = median_price * factor
        rounded = _round_to_five(raw)
        bounds = bounds_by_room.get(room_type, {})
        floor = None if bounds.get("floor_price") in (None, "") else _to_float(bounds.get("floor_price"))
        ceiling = None if bounds.get("ceiling_price") in (None, "") else _to_float(bounds.get("ceiling_price"))
        final = _clamp(float(rounded), floor, ceiling)
        rows.append(
            {
                "room_type_id": room_type,
                "room_type_name": bounds.get("room_type_name") or names.get(room_type) or room_type,
                "raw_baseline_price": round(raw, 2),
                "rounded_baseline_price": rounded,
                "final_baseline_price": final,
                "baseline_basis_days": len(basis_dates_by_room.get(room_type) or set()),
                "basis_price_count": len(values),
                "date_type_factor": factor,
                "date_type_factor_label": factor_label,
                "price_floor": floor,
                "price_ceiling": ceiling,
                "price_guard_source": bounds.get("price_guard_source") or "missing",
            }
        )
    if not rows:
        return {
            "status": "data_gap",
            "hotel_id": args.hotel_id,
            "business_date": business_date,
            "baseline_price_method": "seven_day_room_type_median_x_date_type_factor_v1",
            "pricing_blocked_reason": "baseline_price_requires_effective_room_type_prices",
            "freshness_status": orders_payload.get("freshness_status") or "missing_date",
        }
    return {
        "status": "ok",
        "hotel_id": args.hotel_id,
        "business_date": business_date,
        "data_business_date": business_date,
        "data_snapshot_time": orders_payload.get("data_snapshot_time") or prices_payload.get("data_snapshot_time"),
        "freshness_status": orders_payload.get("freshness_status") or "fresh",
        "baseline_price_method": "seven_day_room_type_median_x_date_type_factor_v1",
        "baseline_price_by_room_type": rows,
        "date_type_factor": factor,
        "date_type_factor_label": factor_label,
    }


def expected_occupancy(args: argparse.Namespace) -> None:
    emit(expected_occupancy_result(args))


def baseline_price(args: argparse.Namespace) -> None:
    emit(baseline_price_result(args))


def _room_price_bounds_from_price_data(args: argparse.Namespace) -> dict | None:
    if not database_source_enabled():
        return None
    result = database_template_result("price_snapshot", args.hotel_id, date=getattr(args, "begin_date", None))
    if result.get("status") != "ok":
        return None
    wanted = str(args.room_type_id).strip()
    wanted_lower = wanted.lower()
    for item in (result.get("payload") or {}).get("price_snapshots") or []:
        candidates = {
            str(item.get("room_type_id") or "").strip(),
            str(item.get("room_type_name") or "").strip(),
        }
        if wanted in candidates or wanted_lower in {candidate.lower() for candidate in candidates if candidate}:
            return {
                "source": "business_dataset_v1.price_data",
                "floor_price": item.get("price_floor"),
                "ceiling_price": item.get("price_ceiling"),
                "matched_room_type_id": item.get("room_type_id"),
                "matched_room_type_name": item.get("room_type_name"),
                "price_freshness_status": (result.get("payload") or {}).get("freshness_status"),
            }
    return None


def _room_price_bounds(db_path: str, hotel_id: str, room_type_id: str) -> dict:
    try:
        with closing(connect(db_path)) as conn:
            row = conn.execute(
                """
                SELECT floor_price, ceiling_price
                FROM room_types
                WHERE hotel_id=? AND room_type_id=?
                """,
                (hotel_id, room_type_id),
            ).fetchone()
    except sqlite3.Error:
        return {"source": "missing", "floor_price": None, "ceiling_price": None}
    if row is None:
        return {"source": "missing", "floor_price": None, "ceiling_price": None}
    return {
        "source": "sqlite_room_types",
        "floor_price": row["floor_price"],
        "ceiling_price": row["ceiling_price"],
    }


def revenue_decision(args: argparse.Namespace) -> None:
    business_date = _business_date(args)
    snapshot = sample_snapshot()
    database_evidence = {}
    expected_occupancy = expected_occupancy_result(args)
    baseline_prices = baseline_price_result(args)
    price_candidate = None
    baseline_rows = baseline_prices.get("baseline_price_by_room_type") or []
    data_is_usable = expected_occupancy.get("status") in {"ok", "historical_only"} and baseline_rows
    data_is_fresh = expected_occupancy.get("status") == "ok" and baseline_prices.get("status") == "ok"
    historical_simulation = bool(data_is_usable and not data_is_fresh)
    if database_source_enabled():
        operating = database_template_result("operating_snapshot", args.hotel_id, date=business_date)
        prices = database_template_result("price_snapshot", args.hotel_id, date=business_date)
        database_evidence = {
            "operating_snapshot": operating,
            "price_snapshot": prices,
            "expected_occupancy": expected_occupancy,
            "baseline_price": baseline_prices,
        }
        if operating.get("status") == "ok":
            snapshot.update(operating.get("payload") or {})
        price_candidate = _select_price_candidate(prices) if _result_is_fresh(operating) and _result_is_fresh(prices) else None

    if data_is_usable and baseline_rows:
        selected = max(baseline_rows, key=lambda item: _to_float(item.get("final_baseline_price")))
        old_price = _to_float((price_candidate or {}).get("current_price"), _to_float(selected.get("final_baseline_price"), 149))
        ceiling = _to_float(selected.get("price_ceiling"), old_price * 1.15) if selected.get("price_ceiling") is not None else old_price * 1.15
        floor = _to_float(selected.get("price_floor"), old_price * 0.85) if selected.get("price_floor") is not None else old_price * 0.85
        occupancy = _to_float(expected_occupancy.get("expected_occupancy_tonight"))
        adjustment = 1.05 if occupancy >= 0.75 else 0.95 if occupancy < 0.45 else 1.0
        new_price = round(_clamp(_round_to_five(_to_float(selected.get("final_baseline_price")) * adjustment), floor, ceiling))
        room_type_id = selected.get("room_type_id") or "KING"
        room_type_name = selected.get("room_type_name") or room_type_id
        mode_text = "生成 OTA 后台门市价 dry-run 建议" if data_is_fresh else "仅生成历史复盘模拟，不允许正式审批或 live 执行"
        reason = f"{expected_occupancy.get('occupancy_basis')} 今晚预期出租率 {occupancy:.2%}，基准价 {selected.get('final_baseline_price')}，{mode_text}。"
    else:
        old_price = None
        new_price = None
        floor = None
        ceiling = None
        room_type_id = "KING"
        room_type_name = "KING"
        reason = "缺少今晚预期出租率或房型基准价，不能生成正式调价建议。"

    guard = price_guard(old_price=old_price, new_price=new_price, floor_price=floor, ceiling_price=ceiling) if data_is_usable else {"passed": False, "violations": ["pricing_input_data_gap"]}
    price_model = (
        _build_ota_price_model(
            new_price,
            getattr(args, "activity_discount_factors", None),
            getattr(args, "pms_price", None),
        )
        if data_is_usable
        else None
    )
    action = {
        "type": "price_update" if data_is_fresh else ("pricing_historical_simulation" if historical_simulation else "pricing_data_gap"),
        "room_type_id": room_type_id,
        "room_type_name": room_type_name,
        "channel": args.channel,
        "begin_date": args.begin_date or today(),
        "end_date": args.end_date or today(),
        "old_price": old_price,
        "normal_price": new_price,
        "weekend_price": round(new_price * 1.1) if new_price is not None else None,
        "price_target_type": price_model["price_target_type"] if price_model else "ota_backend_base_price",
        "ota_base_price": price_model["ota_base_price"] if price_model else None,
        "ota_activity_discount_factor": price_model["ota_activity_discount_factor"] if price_model else None,
        "ota_estimated_final_price": price_model["ota_estimated_final_price"] if price_model else None,
        "pms_price_reference_only": price_model["pms_price_reference_only"] if price_model else getattr(args, "pms_price", None),
        "pms_price_used_for_execution": False,
        "price_model": price_model,
        "reason": reason,
        "guard": guard,
        "expected_occupancy_tonight": expected_occupancy.get("expected_occupancy_tonight"),
        "expected_occupancy_status": expected_occupancy.get("expected_occupancy_status"),
        "baseline_price_method": baseline_prices.get("baseline_price_method"),
    }
    approval_required = bool(data_is_fresh)
    if historical_simulation:
        action["blocked_reason"] = "historical_data_simulation_only"
        action["simulation_only"] = True
    elif not data_is_fresh:
        action["blocked_reason"] = expected_occupancy.get("pricing_blocked_reason") or baseline_prices.get("pricing_blocked_reason") or "pricing_input_data_gap"
    result_status = "ok" if data_is_fresh else ("historical_only" if historical_simulation else "data_gap")

    emit(
        {
            "status": result_status,
            "decision": {
                **standard_envelope(
                    status=result_status,
                    skill_id="S5",
                    summary=(
                        "按今晚预期出租率和房型基准价生成收益建议，默认只做 dry-run，不直接写入渠道。"
                        if data_is_fresh
                        else (
                            "使用历史同日期数据生成调价复盘模拟；不允许创建正式审批或 live 执行。"
                            if historical_simulation
                            else "缺少今晚预期出租率或房型基准价，只能返回数据缺口，不得生成正式调价建议。"
                        )
                    ),
                    evidence={
                        **snapshot,
                        "selected_price_candidate": price_candidate,
                        "database_evidence": database_evidence,
                        "data_business_date": expected_occupancy.get("data_business_date") if data_is_usable else None,
                        "data_snapshot_time": expected_occupancy.get("data_snapshot_time") if data_is_usable else None,
                        "freshness_status": "fresh" if data_is_fresh else (expected_occupancy.get("freshness_status") if historical_simulation else "missing_date"),
                        "business_status": "current" if data_is_fresh else "demo_or_historical",
                        "today_label_allowed": bool(data_is_fresh),
                        "strategy_mode": "expected_tonight_occupancy",
                        "price_model_policy": "adjust_ota_backend_base_price_only",
                        "expected_occupancy": expected_occupancy,
                        "baseline_price": baseline_prices,
                        "baseline_price_by_room_type": baseline_prices.get("baseline_price_by_room_type") or [],
                    },
                    recommendations=(
                        ["先预览 OTA 后台门市价，不直接写入渠道。", "低转化房型先修内容、活动和价格一致性，不急于降价。"]
                        if data_is_fresh
                        else (
                            ["该结果只能用于复盘或演示 dry-run。", "要做今日正式调价，必须接入今日 fresh 预订、续住和价格数据。"]
                            if historical_simulation
                            else ["请先接入今日预订明细、续住/离店明细和价格历史。", "实时在住率、昨日出租率或 sample 数据不得作为调价依据。"]
                        )
                    ),
                    actions=[action],
                    risk_level="medium",
                    approval_required=approval_required,
                ),
                "mode": "dry_run",
                "guards": ["不得低于房型底价", "不得超过单次涨降幅限制", "必须 admin/owner 确认后执行"],
            },
        }
    )


def execute_price(args: argparse.Namespace) -> None:
    auth_context = build_auth_context(
        source=getattr(args, "auth_source", "manual_test"),
        user_id=getattr(args, "user_id", None),
        open_id=getattr(args, "open_id", None),
        union_id=getattr(args, "union_id", None),
        chat_id=getattr(args, "chat_id", None),
        user_role=getattr(args, "user_role", None),
        config_path=getattr(args, "auth_config", None),
    )
    permission = permission_gate(auth_context, "price_update", dry_run=args.dry_run)
    if not permission["allowed"]:
        emit(
            {
                "status": "blocked",
                "reason": permission["reason"],
                "required_permission": permission["required_permission"],
                "auth_context": auth_context,
            }
        )
        return

    gate = approval_gate(
        approved_by=args.approved_by,
        dry_run=args.dry_run,
        action_type="price_update",
        approval_id=getattr(args, "approval_id", None),
        approver_role=getattr(args, "approver_role", None),
    )
    if not gate["allowed"]:
        emit(
            {
                "status": "blocked",
                "reason": gate["reason"],
                "approval_required": gate["approval_required"],
                "auth_context": auth_context,
            }
        )
        return

    if not args.dry_run:
        approval_record = approval_get(args.db, getattr(args, "approval_id", None))
        if not approval_record:
            emit(
                {
                    "status": "blocked",
                    "reason": "approval_record_not_found",
                    "approval_id": getattr(args, "approval_id", None),
                    "auth_context": auth_context,
                }
            )
            return
        payload = approval_record.get("payload") or {}
        if approval_record.get("status") != "approved":
            emit(
                {
                    "status": "blocked",
                    "reason": "approval_record_not_approved",
                    "approval_id": approval_record.get("approval_id"),
                    "approval_status": approval_record.get("status"),
                    "auth_context": auth_context,
                }
            )
            return
        if approval_record.get("action_type") != "price_update":
            emit(
                {
                    "status": "blocked",
                    "reason": "approval_action_type_mismatch",
                    "approval_id": approval_record.get("approval_id"),
                    "approval_action_type": approval_record.get("action_type"),
                }
            )
            return
        if payload.get("freshness_status") != "fresh" or payload.get("business_status") not in (None, "current"):
            emit(
                {
                    "status": "blocked",
                    "reason": "approval_record_data_not_fresh",
                    "approval_id": approval_record.get("approval_id"),
                    "freshness_status": payload.get("freshness_status"),
                    "business_status": payload.get("business_status"),
                }
            )
            return

    guard_source = "cli_args"
    floor_price = getattr(args, "floor_price", None)
    ceiling_price = getattr(args, "ceiling_price", None)
    resolved_room_type_id = args.room_type_id
    if floor_price is None or ceiling_price is None:
        bounds = _room_price_bounds_from_price_data(args) or _room_price_bounds(args.db, args.hotel_id, args.room_type_id)
        if bounds.get("matched_room_type_id"):
            resolved_room_type_id = bounds["matched_room_type_id"]
        if floor_price is None and bounds.get("floor_price") is not None:
            floor_price = float(bounds["floor_price"])
            guard_source = bounds["source"]
        if ceiling_price is None and bounds.get("ceiling_price") is not None:
            ceiling_price = float(bounds["ceiling_price"])
            guard_source = bounds["source"]

    missing_guard_fields = []
    if floor_price is None:
        missing_guard_fields.append("floor_price")
    if ceiling_price is None:
        missing_guard_fields.append("ceiling_price")
    if missing_guard_fields and not args.dry_run:
        emit(
            {
                "status": "blocked",
                "reason": "price_guard_config_missing_for_live",
                "missing_guard_fields": missing_guard_fields,
                "guard_source": guard_source,
                "auth_context": auth_context,
            }
        )
        return
    if missing_guard_fields and args.dry_run:
        emit(
            {
                "status": "dry_run",
                "reason": "price_guard_config_missing",
                "missing_guard_fields": missing_guard_fields,
                "guard_source": guard_source,
                "live_call": False,
                "message": "补齐房型 floor_price/ceiling_price 后才能生成可执行 dry-run 请求。",
            }
        )
        return

    guard = price_guard(
        old_price=getattr(args, "old_price", None),
        new_price=args.normal_price,
        floor_price=floor_price,
        ceiling_price=ceiling_price,
    )
    guard["guard_source"] = guard_source
    guard["floor_price"] = floor_price
    guard["ceiling_price"] = ceiling_price
    if not guard["passed"]:
        emit({"status": "blocked", "reason": "price_guard_failed", "guard": guard})
        return

    price_model = _build_ota_price_model(
        args.normal_price,
        getattr(args, "activity_discount_factors", None),
        getattr(args, "pms_price", None),
    )
    biz = {
        "Channel": args.channel,
        "OrgId": os.environ.get("BEYONDH_ORG_ID", ""),
        "RoomTypeId": resolved_room_type_id,
        "NormalPrice": args.normal_price,
        "BeginDate": args.begin_date,
        "EndDate": args.end_date,
        "IsSetWeekendPrice": args.weekend_price is not None,
    }
    if args.weekend_price is not None:
        biz["WeekendPrice"] = args.weekend_price

    method = "Price.SetPriceByRoomTypeId"
    if args.dry_run or os.environ.get("BEYONDH_ENABLE_LIVE") != "1":
        request_body = build_beyondh_request(method, biz)
        summary = {
            "adapter_vendor": "beyondh",
            "channel_source": "pms",
            "data_source_type": "beyondh_api",
            "source_capability": "write_dry_run",
            "field_quality": "confirmed" if os.environ.get("BEYONDH_CHANNEL_KEY") else "manual_required",
            "captured_at": now_local(),
            "method": method,
            "body": redacted_request(request_body),
            "domain": os.environ.get("BEYONDH_DOMAIN", ""),
        }
        if not getattr(args, "no_log", False):
            log_api(args.hotel_id, method, summary, {"dry_run": True, "price_model": price_model}, "dry_run", args.db)
        emit(
            {
                "status": "dry_run",
                "request": summary,
                "price_model": price_model,
                "guard": guard,
                "resolved_room_type_id": resolved_room_type_id,
                "approval_status": "dry_run_only",
                "live_call": False,
                "message": "当前仅预览 OTA 后台门市价写入请求；PMS 价仅作参考，不作为执行目标。",
            }
        )
        return

    child = argparse.Namespace(
        method=method,
        biz_content=json.dumps(biz, ensure_ascii=False),
        biz_content_b64=None,
        hotel_id=args.hotel_id,
        dry_run=args.dry_run,
        timeout=args.timeout,
        db=args.db,
        no_log=args.no_log,
    )
    beyondh_call(child)
