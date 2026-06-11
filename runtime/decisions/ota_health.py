from __future__ import annotations

import argparse
import os

from runtime.adapters.database import database_source_enabled, database_template_result
from runtime.common import emit
from runtime.contracts import ota_health_level, standard_envelope
from runtime.decisions.demand import sample_snapshot


def ota_health(args: argparse.Namespace) -> None:
    snapshot = sample_snapshot()
    database_evidence = {}
    if database_source_enabled():
        database_evidence = {
            "operation_diagnosis": database_template_result("operation_diagnosis", args.hotel_id),
            "operating_snapshot": database_template_result("operating_snapshot", args.hotel_id),
            "daily_metrics": database_template_result("daily_metrics", args.hotel_id),
        }
        diagnosis = database_evidence["operation_diagnosis"]
        if diagnosis.get("status") == "ok":
            snapshot.update({key: value for key, value in (diagnosis.get("payload") or {}).items() if value is not None})
        operating = database_evidence["operating_snapshot"]
        if operating.get("status") == "ok":
            snapshot.update(operating.get("payload") or {})
    score = snapshot.get("ota_health_score") or 0
    level = ota_health_level(score)
    business_status = snapshot.get("business_status")
    status = "ok" if business_status == "current" else "historical_only"
    emit(
        standard_envelope(
            status=status,
            skill_id="S14",
            summary=(
                f"OTA 健康为 {level}，当前优先处理确认率、评分、转化和推广余额。"
                if status == "ok"
                else f"当前为演示/历史口径，OTA 健康样例为 {level}，不能作为正式数据库诊断。"
            ),
            evidence={
                "hos_score": snapshot["hos_score"],
                "ota_health_score": score,
                "risk_flags": snapshot["risk_flags"],
                "data_source_type": snapshot.get("data_source_type"),
                "freshness_status": snapshot.get("freshness_status"),
                "data_business_date": snapshot.get("data_business_date"),
                "data_snapshot_time": snapshot.get("data_snapshot_time"),
                "data_age_hours": snapshot.get("data_age_hours"),
                "business_status": business_status,
                "today_label_allowed": snapshot.get("today_label_allowed"),
                "database_evidence": database_evidence,
            },
            recommendations=["先修转化和口碑，再考虑降价。", "推广余额为 0 时应列入运营任务。"],
            actions=[
                {"type": "ab_task", "owner": "运营", "task": "检查美团 OTA 内容完整度、确认率和转化漏斗。"},
                {"type": "frontdesk_task", "owner": "前台", "task": "晚高峰前复核外网可售状态。"},
            ],
            risk_level="medium",
        )
    )


def conversion_diagnosis(args: argparse.Namespace) -> None:
    snapshot = sample_snapshot()
    database_evidence = {}
    if database_source_enabled():
        database_evidence = {
            "operation_diagnosis": database_template_result("operation_diagnosis", args.hotel_id),
            "daily_metrics": database_template_result("daily_metrics", args.hotel_id),
        }
        diagnosis = database_evidence["operation_diagnosis"]
        if diagnosis.get("status") == "ok":
            snapshot.update({key: value for key, value in (diagnosis.get("payload") or {}).items() if value is not None})
    exposure = snapshot["exposure"]
    views = snapshot["views"]
    clicks = snapshot.get("clicks")
    paid_orders = snapshot.get("paid_orders")
    pay_rate = snapshot["payment_conversion_rate"]
    traffic_problem = bool(exposure < 1000 or views < 100)
    conversion_problem = bool(pay_rate < 0.04)
    debug = bool(getattr(args, "debug", False) or os.environ.get("HOTEL_OTA_FEISHU_DEBUG") == "1")
    evidence = {
        "exposure": exposure,
        "views": views,
        "clicks": clicks,
        "paid_orders": paid_orders,
        "payment_conversion_numerator": snapshot.get("payment_conversion_numerator", paid_orders),
        "payment_conversion_denominator": snapshot.get("payment_conversion_denominator", views),
        "payment_conversion_rate": pay_rate,
        "traffic_problem": traffic_problem,
        "conversion_problem": conversion_problem,
        "promotion_bid": snapshot.get("promotion_bid"),
        "promotion_cost": snapshot.get("promotion_cost"),
        "promotion_budget": snapshot.get("promotion_budget"),
        "promotion_orders": snapshot.get("promotion_orders"),
        "promotion_revenue": snapshot.get("promotion_revenue"),
        "data_source_type": snapshot.get("data_source_type"),
        "freshness_status": snapshot.get("freshness_status"),
        "data_business_date": snapshot.get("data_business_date"),
        "data_snapshot_time": snapshot.get("data_snapshot_time"),
        "data_age_hours": snapshot.get("data_age_hours"),
        "business_status": snapshot.get("business_status"),
        "today_label_allowed": snapshot.get("today_label_allowed"),
        "risk_flags": snapshot.get("risk_flags"),
    }
    if debug:
        evidence["database_evidence"] = database_evidence
    emit(
        standard_envelope(
            status="historical_only" if snapshot.get("business_status") != "current" else "ok",
            skill_id="S14/S9",
            summary="转化诊断为聚合摘要：保留曝光、浏览、点击、支付订单和支付转化率，用于区分流量不足和转化不足。",
            evidence=evidence,
            recommendations=[
                "只有流量不足时，优先补曝光、活动入口和推广预算，不直接降价。",
                "只有转化不足时，才进入价格、活动叠加和内容修复候选。",
            ],
            actions=[{"type": "diagnosis_task", "next_skill": "S14", "priority": "P0/P1"}],
            risk_level="medium",
        )
    )
