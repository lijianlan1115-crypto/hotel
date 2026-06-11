from __future__ import annotations

import argparse

from runtime.adapters.database import database_source_enabled, database_template_result
from runtime.common import emit, json_dumps, now_local, today
from runtime.storage import connect


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


def _hourly_curve(target_orders: int) -> list[dict[str, int]]:
    anchors = [(7, 0.07), (10, 0.2), (12, 0.34), (15, 0.54), (16, 0.62), (18, 0.74), (20, 0.86), (22, 1.0)]
    curve = []
    last = 0
    for hour, ratio in anchors:
        target = max(last, round(target_orders * ratio))
        curve.append({"hour": hour, "target_orders": target})
        last = target
    if curve:
        curve[-1]["target_orders"] = target_orders
    return curve


def _progress_checkpoints(target_orders: int) -> list[dict[str, int | str]]:
    checkpoints = [(12, "midday", 0.34), (16, "afternoon", 0.62), (20, "evening_peak", 0.86)]
    result = []
    last = 0
    for hour, name, ratio in checkpoints:
        target = max(last, round(target_orders * ratio))
        result.append({"hour": hour, "checkpoint": name, "target_orders": target})
        last = target
    return result


def baseline(args: argparse.Namespace) -> None:
    business_date = args.date or today()
    database_evidence = {}
    if database_source_enabled():
        database_evidence = {
            "sales_baseline": database_template_result("sales_baseline", args.hotel_id, date=business_date),
            "daily_metrics": database_template_result("daily_metrics", args.hotel_id, date=business_date),
            "monthly_metrics": database_template_result("monthly_metrics", args.hotel_id, date=business_date),
        }
    sales_baseline = database_evidence.get("sales_baseline", {})
    sales_payload = sales_baseline.get("payload") or {}
    daily = database_evidence.get("daily_metrics", {})
    monthly = database_evidence.get("monthly_metrics", {})
    daily_payload = daily.get("payload") or {}
    if sales_baseline.get("status") == "ok" and sales_payload.get("target_orders"):
        target_orders = max(int(round(float(sales_payload["target_orders"]))), 1)
        target_occupancy_rate = _metric(daily, "occupancy_rate") or 0
        curve = sales_payload.get("hourly_curve") or _hourly_curve(target_orders)
        checkpoints = sales_payload.get("progress_checkpoints") or _progress_checkpoints(target_orders)
        data_source = "business_dataset_v1"
        freshness_status = sales_payload.get("freshness_status") or "missing_date"
        target_basis_date = sales_payload.get("data_business_date")
        target_basis_type = "sales_baseline"
        source_confidence = "high" if freshness_status == "fresh" else "medium"
    else:
        target_orders = int(round(_metric(daily, "room_nights") or 15))
        target_orders = max(target_orders, 1)
        target_occupancy_rate = _metric(daily, "occupancy_rate") or 0.85
        curve = _hourly_curve(target_orders)
        checkpoints = _progress_checkpoints(target_orders)
        data_source = "database" if any(item.get("status") == "ok" for item in database_evidence.values()) else "sample_data"
        freshness_status = _freshness_status(daily) or ("demo_data" if data_source == "sample_data" else "missing_date")
        target_basis_date = daily_payload.get("data_business_date")
        target_basis_type = "previous_day_actual" if data_source == "database" else "sample_history"
        source_confidence = "high" if data_source == "database" and daily.get("status") == "ok" else "low"
    business_status = "current" if freshness_status == "fresh" else "demo_or_historical"
    payload = {
        "business_date": business_date,
        "target_date": business_date,
        "data_business_date": sales_payload.get("data_business_date") or daily_payload.get("data_business_date"),
        "data_snapshot_time": sales_payload.get("data_snapshot_time") or daily_payload.get("data_snapshot_time"),
        "data_age_hours": sales_payload.get("data_age_hours") if sales_payload else daily_payload.get("data_age_hours"),
        "today_label_allowed": bool(sales_payload.get("today_label_allowed") or daily_payload.get("today_label_allowed", False)),
        "target_basis_date": target_basis_date,
        "target_basis_type": target_basis_type,
        "target_freshness": freshness_status,
        "method": "business_dataset_v1_sales_baseline" if data_source == "business_dataset_v1" else ("database_metrics_plus_default_hour_curve_v1" if data_source == "database" else "history_weekday_plus_market_context_v1"),
        "target_orders": target_orders,
        "target_occupancy_rate": round(float(target_occupancy_rate), 4),
        "hourly_curve": curve,
        "progress_checkpoints": checkpoints,
        "progress_checkpoint_policy": "12/16/20 node targets; S16 judges progress by the active node.",
        "confidence": "high" if data_source == "database" else "medium",
        "source_confidence": source_confidence,
        "decision_confidence": "medium" if data_source in {"database", "business_dataset_v1"} else "low",
        "data_source": data_source,
        "freshness_status": freshness_status,
        "business_status": business_status,
        "database_evidence": database_evidence,
        "generated_at": now_local(),
        "notes": ["日目标只使用 fact_daily_metrics 的本日口径；月指标仅作对比证据，不覆盖当天目标"],
    }
    with connect(args.db) as conn:
        conn.execute(
            """
            INSERT INTO baselines (hotel_id, business_date, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(hotel_id, business_date) DO UPDATE SET
              payload_json=excluded.payload_json,
              created_at=excluded.created_at
            """,
            (args.hotel_id, business_date, json_dumps(payload), now_local()),
        )
    emit({"status": "ok", "hotel_id": args.hotel_id, "baseline": payload})
