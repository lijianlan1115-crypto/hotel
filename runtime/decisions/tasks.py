from __future__ import annotations

import argparse

from runtime.adapters.database import database_source_enabled, database_template_result
from runtime.common import emit, today
from runtime.contracts import standard_envelope


def frontdesk_tasks(args: argparse.Namespace) -> None:
    business_date = getattr(args, "date", None) or today()
    tasks = []
    evidence = {"task_mode": "generic_template", "task_count": 0}
    if database_source_enabled():
        reservation = database_template_result("reservation_snapshot", args.hotel_id, date=business_date)
        stayover = database_template_result("stayover_snapshot", args.hotel_id, date=business_date)
        operating = database_template_result("operating_snapshot", args.hotel_id, date=business_date)
        reservation_payload = reservation.get("payload") or {}
        stayover_payload = stayover.get("payload") or {}
        operating_payload = operating.get("payload") or {}
        if reservation.get("status") == "ok" and reservation_payload.get("source_status") == "ok":
            tasks.append(
                {
                    "task_type": "prearrival_summary",
                    "shift": "到店高峰前",
                    "owner": "前台",
                    "content": f"核对今日预抵 {reservation_payload.get('new_arrival_rooms', 0)} 间，只输出聚合数量，不外发行级订单。",
                }
            )
        if stayover.get("status") == "ok" and stayover_payload.get("source_status") == "ok":
            tasks.append(
                {
                    "task_type": "stayover_summary",
                    "shift": "退房检查前",
                    "owner": "前台",
                    "content": f"核对今日续住/在住 {stayover_payload.get('stayover_rooms', 0)} 间，重点确认离店时间变更。",
                }
            )
        if operating.get("status") == "ok":
            tasks.append(
                {
                    "task_type": "availability_summary",
                    "shift": "每2小时",
                    "owner": "前台",
                    "content": f"复核可售 {operating_payload.get('remaining_rooms')} 间、已售 {operating_payload.get('sold_rooms')} 间和外网可售一致性。",
                }
            )
        evidence = {
            "task_mode": "database_aggregate" if tasks else "generic_template",
            "reservation_source_status": reservation_payload.get("source_status"),
            "stayover_source_status": stayover_payload.get("source_status"),
            "operating_status": operating.get("status"),
            "row_level_details_included": False,
        }
    if not tasks:
        tasks = [
            {"task_type": "inventory_report", "shift": "每2小时", "owner": "前台", "content": "通报库存、预抵、预离和外网可售状态"},
            {"task_type": "conversion_check", "shift": "晚高峰前", "owner": "运营", "content": "检查曝光、浏览、支付转化和价格一致性"},
            {"task_type": "review_followup", "shift": "每日", "owner": "店长", "content": "跟进差评和好评任务完成量"},
        ]
        evidence["task_mode"] = "generic_template"
    evidence["task_count"] = len(tasks)
    emit(
        standard_envelope(
            status="ok",
            skill_id="S3/S11",
            summary="已生成前台与运营执行清单；有数据库聚合时优先使用聚合任务，否则返回通用提醒。",
            evidence=evidence,
            recommendations=["任务生成后必须跟踪完成状态、操作人和操作时间。"],
            actions=tasks,
            risk_level="low",
        )
    )
