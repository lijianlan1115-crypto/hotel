from __future__ import annotations

import argparse
import datetime as dt
import json
from contextlib import closing

from runtime.adapters.database import database_source_enabled, database_template_result
from runtime.common import emit, today
from runtime.decisions.demand import sample_snapshot
from runtime.storage import connect


CHECKPOINTS = [
    {"hour": 12, "checkpoint": "midday", "ratio": 0.34},
    {"hour": 16, "checkpoint": "afternoon", "ratio": 0.62},
    {"hour": 20, "checkpoint": "evening_peak", "ratio": 0.86},
]


def _metric(result: dict, key: str) -> float | None:
    if result.get("status") != "ok":
        return None
    value = ((result.get("payload") or {}).get("normalized_metrics") or {}).get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _freshness_status(result: dict) -> str | None:
    if result.get("status") != "ok":
        return None
    return (result.get("payload") or {}).get("freshness_status")


def _latest_baseline(db_path: str, hotel_id: str, business_date: str) -> dict | None:
    try:
        with closing(connect(db_path)) as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM baselines
                WHERE hotel_id=? AND business_date=?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (hotel_id, business_date),
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    try:
        return json.loads(row["payload_json"])
    except json.JSONDecodeError:
        return None


def _first_number(*values) -> float | None:
    for value in values:
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _date_part(value) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text[:10] if len(text) >= 10 else None


def _today_order_count(order_payload: dict, business_date: str) -> int | None:
    orders = order_payload.get("orders") or []
    seen = set()
    for index, order in enumerate(orders):
        basis_date = _date_part(order.get("business_date")) or _date_part(order.get("checkin_time"))
        if basis_date != business_date:
            continue
        price_detail = order.get("price_detail") or {}
        key = (
            order.get("order_id") or f"row-{index}",
            order.get("room_type_name"),
            order.get("checkin_time"),
            price_detail.get("room_fee"),
        )
        seen.add(key)
    return len(seen) if seen else None


def _active_checkpoint(now: dt.datetime | None = None) -> dict:
    current = now or dt.datetime.now()
    if current.hour < 16:
        return CHECKPOINTS[0]
    if current.hour < 20:
        return CHECKPOINTS[1]
    return CHECKPOINTS[2]


def _checkpoint_target_orders(baseline_payload: dict | None, target_orders: int, checkpoint_hour: int) -> int:
    for checkpoint in (baseline_payload or {}).get("progress_checkpoints") or []:
        if int(checkpoint.get("hour", -1)) == checkpoint_hour:
            return max(int(round(float(checkpoint.get("target_orders") or 0))), 1)
    ratio = next((item["ratio"] for item in CHECKPOINTS if item["hour"] == checkpoint_hour), CHECKPOINTS[-1]["ratio"])
    return max(int(round(target_orders * ratio)), 1)


def _traffic_conversion_context(payload: dict) -> dict:
    exposure = _first_number(payload.get("exposure"))
    views = _first_number(payload.get("views"))
    clicks = _first_number(payload.get("clicks"))
    paid_orders = _first_number(payload.get("paid_orders"), payload.get("orders_today"))
    pay_rate = _first_number(payload.get("payment_conversion_rate"))
    traffic_problem = bool((exposure is not None and exposure < 1000) or (views is not None and views < 100))
    conversion_problem = False
    if pay_rate is not None:
        conversion_problem = pay_rate < 0.04
    elif clicks and paid_orders is not None:
        conversion_problem = paid_orders / clicks < 0.08
    return {
        "exposure": exposure,
        "views": views,
        "clicks": clicks,
        "paid_orders": paid_orders,
        "payment_conversion_rate": pay_rate,
        "traffic_problem": traffic_problem,
        "conversion_problem": conversion_problem,
        "problem_basis": "traffic_conversion_metrics" if any(value is not None for value in [exposure, views, clicks, paid_orders, pay_rate]) else "missing_traffic_conversion_metrics",
    }


def _database_template(template: str, hotel_id: str, business_date: str) -> dict:
    try:
        return database_template_result(template, hotel_id, date=business_date)
    except TypeError:
        return database_template_result(template, hotel_id)


def deviation(args: argparse.Namespace) -> None:
    target_date = str(getattr(args, "date", None) or today())[:10]
    payload = sample_snapshot()
    database_evidence = {}
    if database_source_enabled():
        database_evidence = {
            "operating_snapshot": _database_template("operating_snapshot", args.hotel_id, target_date),
            "operation_diagnosis": _database_template("operation_diagnosis", args.hotel_id, target_date),
            "order_snapshot": _database_template("order_snapshot", args.hotel_id, target_date),
            "daily_metrics": _database_template("daily_metrics", args.hotel_id, target_date),
            "monthly_metrics": _database_template("monthly_metrics", args.hotel_id, target_date),
        }
        operating = database_evidence["operating_snapshot"]
        if operating.get("status") == "ok":
            payload.update(operating.get("payload") or {})
        operation = database_evidence["operation_diagnosis"]
        if operation.get("status") == "ok":
            payload.update(operation.get("payload") or {})

    daily = database_evidence.get("daily_metrics", {})
    daily_payload = daily.get("payload") or {}
    operating_payload = (database_evidence.get("operating_snapshot", {}) or {}).get("payload") or {}
    order_result = database_evidence.get("order_snapshot", {}) or {}
    order_payload = order_result.get("payload") or {}
    baseline_payload = _latest_baseline(args.db, args.hotel_id, target_date)

    target_source = "daily_metrics.previous_day_room_nights"
    target_basis_date = daily_payload.get("data_business_date")
    target_freshness = _freshness_status(daily) or "missing_date"
    if baseline_payload and baseline_payload.get("target_orders"):
        target_orders = int(round(float(baseline_payload["target_orders"])))
        target_source = "baselines.target_orders"
        target_basis_date = baseline_payload.get("target_basis_date") or baseline_payload.get("data_business_date")
        target_freshness = baseline_payload.get("freshness_status") or target_freshness
    else:
        target_orders = int(round(_metric(daily, "room_nights") or 15))
    target_orders = max(target_orders, 1)

    order_actual = _today_order_count(order_payload, target_date) if order_result.get("status") == "ok" else None
    actual_orders_value = order_actual
    actual_source = None
    actual_basis_date = None
    actual_freshness = _freshness_status(order_result) or "missing_date"
    actual_trusted = False
    if actual_orders_value is not None:
        actual_orders = actual_orders_value
        actual_source = "order_snapshot.business_date_or_checkin_time"
        actual_basis_date = order_payload.get("data_business_date") or target_date
        actual_trusted = actual_freshness == "fresh" and actual_basis_date == target_date
    else:
        actual_orders_value = _first_number(
            operating_payload.get("orders_today"),
            operating_payload.get("sold_rooms_today"),
            payload.get("orders_today") if payload.get("data_source_type") != "sample_data" else None,
        )
        actual_freshness = _freshness_status(database_evidence.get("operating_snapshot", {})) or "missing_date"
        if actual_orders_value is not None:
            actual_orders = actual_orders_value
            actual_source = "operating_snapshot.orders_today_or_sold_rooms_today"
            actual_basis_date = operating_payload.get("data_business_date") or payload.get("data_business_date")
            actual_trusted = actual_freshness == "fresh" and actual_basis_date == target_date
        else:
            actual_orders = _first_number(operating_payload.get("sold_rooms"), operating_payload.get("occupied_rooms")) or 0
            actual_source = "operating_snapshot.current_occupied_rooms_proxy"
            actual_basis_date = operating_payload.get("data_business_date") or payload.get("data_business_date")
            actual_trusted = False

    progress_checkpoint = _active_checkpoint()
    checkpoint_target_orders = _checkpoint_target_orders(baseline_payload, target_orders, int(progress_checkpoint["hour"]))
    daily_completion = float(actual_orders) / target_orders
    checkpoint_completion = float(actual_orders) / checkpoint_target_orders
    context = _traffic_conversion_context({**payload, **operating_payload})
    retrospective_completion = None
    historical_progress_mode = False

    if checkpoint_completion >= 0.9:
        direction = "ahead"
        recommendation = "节点进度领先。若数据为今日实时口径，继续观察晚高峰；若为历史数据，仅用于复盘。"
        downstream = "S5"
    elif checkpoint_completion >= 0.65:
        direction = "normal"
        recommendation = "节点进度正常。优先维护内容、库存和价格一致性，不急于降价。"
        downstream = "S14"
    else:
        direction = "behind"
        if context["traffic_problem"] and not context["conversion_problem"]:
            recommendation = "节点进度落后且流量不足，先补曝光、推广入口和活动资源，不直接降价。"
            downstream = "S9/S14"
        elif context["conversion_problem"]:
            recommendation = "节点进度落后且转化不足，先排查价格一致性、活动叠加和内容页，必要时再进入调价候选。"
            downstream = "S14/S5"
        else:
            recommendation = "节点进度落后，但缺少流量/转化分子分母证据；先补数据，再判断是否需要调价。"
            downstream = "S14"

    if not actual_trusted:
        if actual_basis_date == target_date and actual_orders is not None and target_orders > 0:
            retrospective_completion = float(actual_orders) / target_orders
            historical_progress_mode = True
        daily_completion = None
        checkpoint_completion = None
        direction = "data_gap"
        context = {
            "traffic_problem": None,
            "conversion_problem": None,
            "problem_basis": "actual_orders_not_today_realtime",
        }
        recommendation = (
            "该日期只能做历史日终复盘，不能当作实时节点进度；"
            "流量/转化判断和 S5 调价交接均已阻断。"
            if historical_progress_mode
            else "实际订单不是同日期 fresh 实时口径；完成率、流量/转化判断和 S5 交接均已阻断。"
        )
        downstream = "S14"

    metrics_freshness = _freshness_status(daily)
    freshness_status = actual_freshness if actual_trusted else (metrics_freshness or "missing_date")
    target_same_date = target_basis_date in (None, target_date)
    target_trusted = (
        target_orders > 0
        and target_source in {"baselines.target_orders", "daily_metrics.previous_day_room_nights"}
        and target_same_date
        and target_freshness not in {"demo_data", "missing_date"}
    )
    downstream_allowed = bool(actual_trusted and target_trusted)
    business_status = "current" if downstream_allowed else "demo_or_historical"
    downstream_blocked_reason = None
    if not actual_trusted:
        downstream_blocked_reason = "actual_orders_not_today_realtime"
    elif not target_trusted:
        downstream_blocked_reason = "target_orders_not_trusted"
    pricing_candidate_allowed = bool(downstream_allowed and direction == "behind" and context["conversion_problem"] and not context["traffic_problem"])
    completion_rate = round(checkpoint_completion, 4) if checkpoint_completion is not None else None
    daily_completion_rate = round(daily_completion, 4) if daily_completion is not None else None

    emit(
        {
            "status": "ok" if downstream_allowed else "data_gap",
            "hotel_id": args.hotel_id,
            "target_date": target_date,
            "direction": direction,
            "completion_rate": completion_rate,
            "daily_completion_rate": daily_completion_rate,
            "retrospective_completion_rate": round(retrospective_completion, 4) if retrospective_completion is not None else None,
            "historical_progress_mode": historical_progress_mode,
            "actual_orders": actual_orders,
            "target_orders": target_orders,
            "progress_checkpoint": progress_checkpoint,
            "checkpoint_target_orders": checkpoint_target_orders,
            "checkpoint_completion_rate": completion_rate,
            "actual_source": actual_source,
            "target_source": target_source,
            "actual_basis_date": actual_basis_date,
            "target_basis_date": target_basis_date,
            "field_freshness": {
                "actual_orders": actual_freshness,
                "target_orders": target_freshness,
                "daily_metrics": metrics_freshness,
            },
            "traffic_problem": context["traffic_problem"],
            "conversion_problem": context["conversion_problem"],
            "traffic_conversion_evidence": context,
            "pricing_candidate_allowed": pricing_candidate_allowed,
            "room_availability_policy": "入住销量按入住当夜统计；次日 14:00 前退房且未续住的房间按当日可售处理。",
            "downstream_allowed": downstream_allowed,
            "downstream_blocked_reason": downstream_blocked_reason,
            "data_source": "database" if any(item.get("status") == "ok" for item in database_evidence.values()) else "sample_data",
            "freshness_status": freshness_status,
            "business_status": business_status,
            "data_business_date": actual_basis_date or daily_payload.get("data_business_date") or payload.get("data_business_date"),
            "data_snapshot_time": operating_payload.get("data_snapshot_time") or daily_payload.get("data_snapshot_time") or payload.get("data_snapshot_time"),
            "data_age_hours": operating_payload.get("data_age_hours") or daily_payload.get("data_age_hours") or payload.get("data_age_hours"),
            "today_label_allowed": bool(downstream_allowed),
            "evidence": {**payload, "database_evidence": database_evidence},
            "recommendations": [recommendation],
            "downstream_skill": downstream if downstream_allowed else "S14",
        }
    )
