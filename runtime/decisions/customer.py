from __future__ import annotations

import argparse
from typing import Any

from runtime.adapters.database import database_source_enabled, database_template_result
from runtime.common import emit
from runtime.contracts import standard_envelope


def _to_float(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _group_bucket(buckets: dict[str, dict[str, Any]], key: str, room_fee: float, room_nights: float) -> None:
    bucket = buckets.setdefault(key or "unknown", {"count": 0, "room_fee": 0.0, "room_nights": 0.0})
    bucket["count"] += 1
    bucket["room_fee"] += room_fee
    bucket["room_nights"] += room_nights


def _finalize_buckets(buckets: dict[str, dict[str, Any]], total_count: int) -> list[dict[str, Any]]:
    rows = []
    for key, bucket in sorted(buckets.items(), key=lambda item: item[1]["count"], reverse=True):
        nights = bucket["room_nights"] or bucket["count"] or 1
        rows.append(
            {
                "name": key,
                "order_count": bucket["count"],
                "share": round(bucket["count"] / total_count, 4) if total_count else 0,
                "adr": round(bucket["room_fee"] / nights, 2) if bucket["room_fee"] else 0,
            }
        )
    return rows


def customer_analysis(args: argparse.Namespace) -> None:
    if not database_source_enabled():
        emit(
            standard_envelope(
                status="data_gap",
                skill_id="S17",
                summary="客户订单分析需要数据库订单聚合；当前数据库来源未启用。",
                evidence={"blocked_reason": "database_source_disabled"},
                recommendations=["请先确认 systemd/CLI 已加载 MySQL 数据源环境变量。"],
                risk_level="medium",
            )
        )
        return

    result = database_template_result("order_snapshot", args.hotel_id)
    if result.get("status") != "ok":
        emit(
            standard_envelope(
                status="data_gap",
                skill_id="S17",
                summary="客户订单分析无法读取订单快照。",
                evidence={"database_result_status": result.get("status"), "reason": result.get("reason")},
                recommendations=["请先检查数据库映射、只读账号和 order_snapshot 模板。"],
                risk_level="medium",
            )
        )
        return

    payload = result.get("payload") or {}
    orders = payload.get("orders") or []
    seen = set()
    unique_orders = []
    for index, order in enumerate(orders):
        price_detail = order.get("price_detail") or {}
        key = (
            order.get("order_id") or f"row-{index}",
            order.get("room_type_name"),
            order.get("checkin_time"),
            price_detail.get("room_fee"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_orders.append(order)

    channel_buckets: dict[str, dict[str, Any]] = {}
    room_type_buckets: dict[str, dict[str, Any]] = {}
    total_fee = 0.0
    total_nights = 0.0
    for order in unique_orders:
        price_detail = order.get("price_detail") or {}
        room_fee = _to_float(price_detail.get("room_fee"))
        room_nights = _to_float(order.get("room_nights"), 1) or 1
        total_fee += room_fee
        total_nights += room_nights
        _group_bucket(channel_buckets, str(order.get("customer_source") or "unknown"), room_fee, room_nights)
        _group_bucket(room_type_buckets, str(order.get("room_type_name") or order.get("room_type_id") or "unknown"), room_fee, room_nights)

    total_count = len(unique_orders)
    evidence = {
        "record_count": len(orders),
        "unique_order_count": total_count,
        "overall_adr": round(total_fee / (total_nights or total_count or 1), 2) if total_fee else 0,
        "channel_distribution": _finalize_buckets(channel_buckets, total_count),
        "room_type_distribution": _finalize_buckets(room_type_buckets, total_count),
        "data_business_date": payload.get("data_business_date"),
        "data_snapshot_time": payload.get("data_snapshot_time"),
        "data_age_hours": payload.get("data_age_hours"),
        "freshness_status": payload.get("freshness_status"),
        "business_status": payload.get("business_status"),
        "today_label_allowed": payload.get("today_label_allowed"),
        "data_source_type": result.get("data_source_type"),
        "field_quality": result.get("field_quality"),
        "privacy_policy": "aggregate_only_no_row_level_orders",
        "row_level_orders_included": False,
    }
    emit(
        standard_envelope(
            status="ok" if total_count else "data_gap",
            skill_id="S17",
            summary="客户订单分析只输出聚合统计，不展示行级订单明细。",
            evidence=evidence,
            recommendations=["如需订单明细，请走受控报表/BI/数据库只读流程，不通过飞书聊天外发。"],
            actions=[{"type": "customer_order_analysis", "privacy": "aggregate_only"}],
            risk_level="medium",
        )
    )
