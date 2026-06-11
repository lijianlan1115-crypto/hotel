from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json
import uuid
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Callable

from runtime.common import emit, json_dumps, now_local, today
from runtime.decisions.baseline import baseline
from runtime.decisions.calendar import calendar_query
from runtime.decisions.customer import customer_analysis
from runtime.decisions.demand import snapshot
from runtime.decisions.deviation import deviation
from runtime.decisions.ota_health import conversion_diagnosis, ota_health
from runtime.decisions.pricing import execute_price, revenue_decision
from runtime.decisions.tasks import frontdesk_tasks
from runtime.safety.auth import build_auth_context, permission_gate
from runtime.safety.feishu_output import feishu_output_gate
from runtime.storage import connect


MENU_TTL_MINUTES = 5
ACTIVE_MENU_STATUSES = ("active", "awaiting_params")


@dataclass(frozen=True)
class MenuCommand:
    command_id: str
    title: str
    permission_action: str
    risk_level: str
    readonly: bool
    dry_run: bool
    approval_required: bool
    usage: str
    handler: Callable[[argparse.Namespace, list[str]], dict[str, Any]]
    min_args: int = 0


def _capture_json(func: Callable[[argparse.Namespace], None], namespace: argparse.Namespace) -> dict[str, Any]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        func(namespace)
    output = buffer.getvalue().strip()
    if not output:
        return {"status": "error", "message": "runtime_command_returned_empty_output"}
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        return {"status": "error", "message": f"runtime_command_returned_invalid_json:{exc.msg}"}


def _schema(db_path: str) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS command_menus (
                  menu_id TEXT PRIMARY KEY,
                  chat_id TEXT NOT NULL,
                  starter_open_id TEXT NOT NULL,
                  starter_role TEXT NOT NULL,
                  hotel_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  selected_command_id TEXT,
                  expires_at TEXT NOT NULL,
                  payload_json TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_command_menus_chat_status
                  ON command_menus(chat_id, status, expires_at);
                CREATE INDEX IF NOT EXISTS idx_command_menus_owner_status
                  ON command_menus(chat_id, starter_open_id, status, expires_at);
                """
            )


def _expires_at() -> str:
    return (dt.datetime.now() + dt.timedelta(minutes=MENU_TTL_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")


def _is_expired(expires_at: str) -> bool:
    return expires_at < now_local()


def _starter_id(args: argparse.Namespace) -> str | None:
    return getattr(args, "open_id", None) or getattr(args, "user_id", None) or getattr(args, "union_id", None)


def _auth_context(args: argparse.Namespace) -> dict[str, Any]:
    return build_auth_context(
        source=getattr(args, "source", "feishu"),
        user_id=getattr(args, "user_id", None),
        open_id=getattr(args, "open_id", None),
        union_id=getattr(args, "union_id", None),
        chat_id=getattr(args, "chat_id", None),
        user_role=getattr(args, "user_role", None),
        config_path=getattr(args, "auth_config", None),
    )


def _safe_summary(result: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "status": result.get("status"),
        "summary": result.get("summary"),
        "business_status": result.get("business_status"),
        "freshness_status": result.get("freshness_status"),
        "data_business_date": result.get("data_business_date"),
        "data_snapshot_time": result.get("data_snapshot_time"),
        "today_label_allowed": result.get("today_label_allowed"),
    }
    if result.get("business_summary"):
        summary["business_summary"] = result.get("business_summary")
    if result.get("direction"):
        summary.update(
            {
                "direction": result.get("direction"),
                "progress_checkpoint": result.get("progress_checkpoint"),
                "checkpoint_target_orders": result.get("checkpoint_target_orders"),
                "checkpoint_completion_rate": result.get("checkpoint_completion_rate"),
                "retrospective_completion_rate": result.get("retrospective_completion_rate"),
                "historical_progress_mode": result.get("historical_progress_mode"),
                "traffic_problem": result.get("traffic_problem"),
                "conversion_problem": result.get("conversion_problem"),
                "downstream_allowed": result.get("downstream_allowed"),
                "downstream_blocked_reason": result.get("downstream_blocked_reason"),
            }
        )
    if result.get("baseline"):
        baseline_payload = result["baseline"]
        summary["baseline"] = {
            "business_date": baseline_payload.get("business_date"),
            "target_orders": baseline_payload.get("target_orders"),
            "progress_checkpoints": baseline_payload.get("progress_checkpoints"),
            "freshness_status": baseline_payload.get("freshness_status"),
            "business_status": baseline_payload.get("business_status"),
        }
    if result.get("date"):
        summary["calendar"] = {
            "date": result.get("date"),
            "is_weekend": result.get("is_weekend"),
            "is_workday": result.get("is_workday"),
            "is_holiday": result.get("is_holiday"),
            "is_adjusted_workday": result.get("is_adjusted_workday"),
            "holiday_name": result.get("holiday_name"),
            "demand_level": result.get("demand_level"),
            "price_advice": result.get("price_advice"),
        }
    if result.get("skill_id"):
        summary.update(
            {
                "skill_id": result.get("skill_id"),
                "risk_level": result.get("risk_level"),
                "approval_required": result.get("approval_required"),
                "recommendations": result.get("recommendations"),
            }
        )
    if result.get("decision"):
        decision = result["decision"]
        summary["decision"] = {
            "status": decision.get("status"),
            "summary": decision.get("summary"),
            "approval_required": decision.get("approval_required"),
            "actions": decision.get("actions"),
            "risk_level": decision.get("risk_level"),
        }
    if result.get("price_model"):
        summary["price_model"] = result.get("price_model")
        summary["live_call"] = result.get("live_call")
        summary["approval_status"] = result.get("approval_status")
        summary["guard"] = result.get("guard")
    if result.get("evidence"):
        evidence = result["evidence"]
        summary["evidence"] = {
            key: evidence.get(key)
            for key in [
                "unique_order_count",
                "channel_share",
                "room_type_share",
                "adr",
                "row_level_orders_included",
                "exposure",
                "views",
                "clicks",
                "paid_orders",
                "payment_conversion_rate",
                "traffic_problem",
                "conversion_problem",
            ]
            if key in evidence
        }
    return {key: value for key, value in summary.items() if value is not None}


def _parse_price_token(value: str | float | int | None) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", "")
    for marker in ("元", "￥", "¥", "RMB", "rmb"):
        text = text.replace(marker, "")
    try:
        return float(text.strip())
    except ValueError:
        return None


def _render_final_reply(command: MenuCommand, result_summary: dict[str, Any]) -> str:
    status = result_summary.get("status", "unknown")
    if status == "ok":
        conclusion = f"已完成 {command.title} 查询/预览。"
    elif status == "historical_only":
        conclusion = f"{command.title} 只完成历史复盘，不能作为今日正式结论。"
    elif status == "data_gap":
        conclusion = f"{command.title} 数据不足，未生成正式建议。"
    elif status == "blocked":
        conclusion = f"{command.title} 已被安全或权限规则阻断。"
    elif status == "error":
        conclusion = f"{command.title} 执行失败。"
    else:
        conclusion = f"{command.title} 返回状态 {status}。"
    approval = result_summary.get("approval_status") or ("需要审批" if command.approval_required and status == "ok" else "不可审批" if status in {"data_gap", "historical_only", "blocked", "error"} else "无需审批")
    suggestion = "如需真实执行，请继续发起审批。" if command.approval_required and status == "ok" else "按风险提示补齐数据或仅做复盘，不要直接执行。"
    return (
        f"结论：{conclusion}\n"
        f"数据：状态 {status}，新鲜度 {result_summary.get('freshness_status', 'unknown')}。\n"
        "证据：只展示脱敏摘要，完整 runtime JSON 不在飞书外发。\n"
        "风险：写动作仍只允许 dry-run 或审批链路。\n"
        f"建议：{suggestion}\n"
        f"审批：{approval}"
    )


def _handle_snapshot(base: argparse.Namespace, tokens: list[str]) -> dict[str, Any]:
    return _capture_json(snapshot, argparse.Namespace(db=base.db, hotel_id=base.hotel_id, source="menu"))


def _handle_deviation(base: argparse.Namespace, tokens: list[str]) -> dict[str, Any]:
    return _capture_json(deviation, argparse.Namespace(db=base.db, hotel_id=base.hotel_id, date=tokens[0] if tokens else None))


def _handle_baseline(base: argparse.Namespace, tokens: list[str]) -> dict[str, Any]:
    date = tokens[0] if tokens else None
    return _capture_json(baseline, argparse.Namespace(db=base.db, hotel_id=base.hotel_id, date=date))


def _handle_calendar(base: argparse.Namespace, tokens: list[str]) -> dict[str, Any]:
    date = tokens[0] if tokens else today()
    return _capture_json(calendar_query, argparse.Namespace(db=base.db, date=date))


def _handle_ota_health(base: argparse.Namespace, tokens: list[str]) -> dict[str, Any]:
    return _capture_json(ota_health, argparse.Namespace(hotel_id=base.hotel_id))


def _handle_conversion(base: argparse.Namespace, tokens: list[str]) -> dict[str, Any]:
    return _capture_json(conversion_diagnosis, argparse.Namespace(hotel_id=base.hotel_id, debug=False))


def _handle_revenue(base: argparse.Namespace, tokens: list[str]) -> dict[str, Any]:
    pms_price = _parse_price_token(tokens[4]) if len(tokens) > 4 else None
    if len(tokens) > 4 and pms_price is None:
        return {"status": "error", "message": "pms_price_format_invalid", "expected": "159 / 159元 / ￥159"}
    return _capture_json(
        revenue_decision,
        argparse.Namespace(
            hotel_id=base.hotel_id,
            channel=tokens[0] if tokens else "Mtop",
            begin_date=tokens[1] if len(tokens) > 1 else None,
            end_date=tokens[2] if len(tokens) > 2 else None,
            activity_discount_factors=tokens[3] if len(tokens) > 3 else None,
            pms_price=pms_price,
        ),
    )


def _handle_execute_price(base: argparse.Namespace, tokens: list[str]) -> dict[str, Any]:
    room_type_id, channel, normal_price, begin_date = tokens[:4]
    end_date = tokens[4] if len(tokens) > 4 else begin_date
    activity_discount_factors = tokens[5] if len(tokens) > 5 else None
    parsed_normal_price = _parse_price_token(normal_price)
    pms_price = _parse_price_token(tokens[6]) if len(tokens) > 6 else None
    if parsed_normal_price is None:
        return {"status": "error", "message": "normal_price_format_invalid", "expected": "159 / 159元 / ￥159"}
    if len(tokens) > 6 and pms_price is None:
        return {"status": "error", "message": "pms_price_format_invalid", "expected": "159 / 159元 / ￥159"}
    return _capture_json(
        execute_price,
        argparse.Namespace(
            db=base.db,
            hotel_id=base.hotel_id,
            room_type_id=room_type_id,
            channel=channel,
            normal_price=parsed_normal_price,
            weekend_price=None,
            begin_date=begin_date,
            end_date=end_date,
            approved_by=None,
            approval_id=None,
            approver_role=None,
            old_price=None,
            floor_price=None,
            ceiling_price=None,
            activity_discount_factors=activity_discount_factors,
            pms_price=pms_price,
            dry_run=True,
            no_log=True,
            timeout=20,
            auth_source=base.source,
            user_id=base.user_id,
            open_id=base.open_id,
            union_id=base.union_id,
            chat_id=base.chat_id,
            user_role=base.user_role,
            auth_config=base.auth_config,
        ),
    )


def _handle_customer(base: argparse.Namespace, tokens: list[str]) -> dict[str, Any]:
    return _capture_json(customer_analysis, argparse.Namespace(hotel_id=base.hotel_id))


def _handle_frontdesk(base: argparse.Namespace, tokens: list[str]) -> dict[str, Any]:
    return _capture_json(frontdesk_tasks, argparse.Namespace(hotel_id=base.hotel_id, date=tokens[0] if tokens else None))


COMMANDS: tuple[MenuCommand, ...] = (
    MenuCommand("1", "经营快报", "view_diagnosis", "low", True, False, False, "1", _handle_snapshot),
    MenuCommand("2", "进度诊断", "view_diagnosis", "low", True, False, False, "2 [日期]", _handle_deviation),
    MenuCommand("3", "销售基准线", "view_diagnosis", "low", True, False, False, "3 [日期]", _handle_baseline),
    MenuCommand("4", "业务日历/行情日期", "view_diagnosis", "low", True, False, False, "4 [日期]", _handle_calendar),
    MenuCommand("5", "OTA 健康诊断", "view_diagnosis", "low", True, False, False, "5", _handle_ota_health),
    MenuCommand("6", "流量转化诊断", "view_diagnosis", "low", True, False, False, "6", _handle_conversion),
    MenuCommand("7", "调价建议", "run_recommendation", "medium", True, False, False, "7 [渠道] [开始日期] [结束日期] [折扣系数] [PMS参考价]", _handle_revenue),
    MenuCommand("8", "调价 dry-run", "create_dry_run", "high", False, True, False, "8 房型 渠道 后台价 开始日期 [结束日期] [折扣系数] [PMS参考价]", _handle_execute_price, min_args=4),
    MenuCommand("9", "客户/订单聚合分析", "view_diagnosis", "medium", True, False, False, "9", _handle_customer),
    MenuCommand("10", "前台任务", "view_frontdesk_task", "low", True, False, False, "10 [日期]", _handle_frontdesk),
)
COMMAND_BY_ID = {command.command_id: command for command in COMMANDS}


def _command_public(command: MenuCommand) -> dict[str, Any]:
    return {
        "id": command.command_id,
        "title": command.title,
        "permission": command.permission_action,
        "risk_level": command.risk_level,
        "readonly": command.readonly,
        "dry_run": command.dry_run,
        "approval_required": command.approval_required,
        "usage": command.usage,
    }


def _available_commands(auth_context: dict[str, Any]) -> list[MenuCommand]:
    available = []
    for command in COMMANDS:
        gate = permission_gate(auth_context, command.permission_action, dry_run=command.dry_run)
        if gate["allowed"]:
            available.append(command)
    return available


def _menu_message(commands: list[MenuCommand], expires_at: str) -> str:
    lines = ["您好，可以回复以下编号执行任务："]
    lines.extend(f"{command.command_id}. {command.title} - 用法：{command.usage}" for command in commands)
    lines.append("0. 取消当前菜单")
    lines.append(f"有效期至：{expires_at}")
    return "\n".join(lines)


def _insert_menu(args: argparse.Namespace, auth_context: dict[str, Any], commands: list[MenuCommand]) -> tuple[str, str]:
    menu_id = f"menu-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    expires_at = _expires_at()
    now = now_local()
    starter_id = _starter_id(args) or ""
    payload = {"available_command_ids": [command.command_id for command in commands]}
    with closing(connect(args.db)) as conn:
        with conn:
            conn.execute(
                """
                UPDATE command_menus
                SET status='cancelled', updated_at=?
                WHERE chat_id=? AND starter_open_id=? AND status IN ('active','awaiting_params')
                """,
                (now, args.chat_id, starter_id),
            )
            conn.execute(
                """
                INSERT INTO command_menus
                  (menu_id, chat_id, starter_open_id, starter_role, hotel_id, status, selected_command_id, expires_at, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'active', NULL, ?, ?, ?, ?)
                """,
                (
                    menu_id,
                    args.chat_id,
                    starter_id,
                    auth_context.get("user_role", "guest"),
                    args.hotel_id,
                    expires_at,
                    json_dumps(payload),
                    now,
                    now,
                ),
            )
    return menu_id, expires_at


def _latest_menu_for_owner(db_path: str, chat_id: str, starter_id: str) -> dict[str, Any] | None:
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM command_menus
            WHERE chat_id=? AND starter_open_id=? AND status IN ('active','awaiting_params')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (chat_id, starter_id),
        ).fetchone()
    return dict(row) if row else None


def _latest_menu_in_chat(db_path: str, chat_id: str) -> dict[str, Any] | None:
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM command_menus
            WHERE chat_id=? AND status IN ('active','awaiting_params')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (chat_id,),
        ).fetchone()
    return dict(row) if row else None


def _update_menu(db_path: str, menu_id: str, *, status: str, selected_command_id: str | None = None) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                "UPDATE command_menus SET status=?, selected_command_id=COALESCE(?, selected_command_id), updated_at=? WHERE menu_id=?",
                (status, selected_command_id, now_local(), menu_id),
            )


def _parse_reply(reply: str) -> tuple[str | None, list[str]]:
    parts = str(reply or "").strip().split()
    while parts and parts[0].startswith("@"):
        parts.pop(0)
    if not parts:
        return None, []
    return parts[0], parts[1:]


def command_menu_start(args: argparse.Namespace) -> None:
    _schema(args.db)
    auth_context = _auth_context(args)
    starter_id = _starter_id(args)
    if not starter_id:
        emit(
            {
                "status": "blocked",
                "blocked_reason": "missing_menu_owner_identity",
                "template_id": "permission-denied",
                "auth_context": auth_context,
            }
        )
        return
    if auth_context.get("auth_status") != "authorized":
        emit(
            {
                "status": "blocked",
                "blocked_reason": auth_context.get("reason", "permission_denied"),
                "template_id": "permission-denied",
                "auth_context": auth_context,
            }
        )
        return
    commands = _available_commands(auth_context)
    if not commands:
        emit(
            {
                "status": "blocked",
                "blocked_reason": "no_available_commands_for_role",
                "template_id": "permission-denied",
                "starter_role": auth_context.get("user_role"),
                "auth_context": auth_context,
            }
        )
        return
    menu_id, expires_at = _insert_menu(args, auth_context, commands)
    message = _menu_message(commands, expires_at)
    gate = feishu_output_gate(source=args.source, content_kind="text", message=message)
    emit(
        {
            "status": "ok" if gate.get("status") == "ok" else "blocked",
            "menu_id": menu_id,
            "expires_at": expires_at,
            "starter_role": auth_context.get("user_role"),
            "available_commands": [_command_public(command) for command in commands],
            "selected_command": None,
            "execution_status": "waiting_for_reply",
            "blocked_reason": gate.get("blocked_reason"),
            "template_id": "command-menu" if gate.get("status") == "ok" else gate.get("template_id"),
            "message": message if gate.get("status") == "ok" else None,
            "auth_context": auth_context,
        }
    )


def command_menu_reply(args: argparse.Namespace) -> None:
    _schema(args.db)
    auth_context = _auth_context(args)
    starter_id = _starter_id(args)
    if not starter_id:
        emit(
            {
                "status": "blocked",
                "blocked_reason": "missing_menu_owner_identity",
                "template_id": "permission-denied",
                "auth_context": auth_context,
            }
        )
        return
    if auth_context.get("auth_status") != "authorized":
        emit(
            {
                "status": "blocked",
                "blocked_reason": auth_context.get("reason", "permission_denied"),
                "template_id": "permission-denied",
                "auth_context": auth_context,
            }
        )
        return
    menu = _latest_menu_for_owner(args.db, args.chat_id, starter_id)
    if not menu:
        other_menu = _latest_menu_in_chat(args.db, args.chat_id)
        emit(
            {
                "status": "blocked",
                "menu_id": other_menu.get("menu_id") if other_menu else None,
                "starter_role": auth_context.get("user_role"),
                "selected_command": None,
                "execution_status": "blocked",
                "blocked_reason": "menu_owner_mismatch" if other_menu else "no_active_menu",
                "template_id": "command-menu-error",
                "auth_context": auth_context,
            }
        )
        return
    if _is_expired(menu["expires_at"]):
        _update_menu(args.db, menu["menu_id"], status="expired")
        emit(
            {
                "status": "blocked",
                "menu_id": menu["menu_id"],
                "expires_at": menu["expires_at"],
                "starter_role": menu["starter_role"],
                "selected_command": None,
                "execution_status": "blocked",
                "blocked_reason": "menu_expired",
                "template_id": "command-menu-error",
                "auth_context": auth_context,
            }
        )
        return
    command_id, tokens = _parse_reply(args.reply)
    if command_id == "0":
        _update_menu(args.db, menu["menu_id"], status="cancelled", selected_command_id="0")
        emit(
            {
                "status": "ok",
                "menu_id": menu["menu_id"],
                "expires_at": menu["expires_at"],
                "starter_role": menu["starter_role"],
                "selected_command": {"id": "0", "title": "取消当前菜单"},
                "execution_status": "cancelled",
                "blocked_reason": None,
                "template_id": "command-menu-cancelled",
                "auth_context": auth_context,
            }
        )
        return
    command = COMMAND_BY_ID.get(command_id or "")
    if not command:
        emit(
            {
                "status": "blocked",
                "menu_id": menu["menu_id"],
                "expires_at": menu["expires_at"],
                "starter_role": menu["starter_role"],
                "selected_command": None,
                "execution_status": "blocked",
                "blocked_reason": "unknown_menu_command",
                "template_id": "command-menu-error",
                "auth_context": auth_context,
            }
        )
        return
    gate = permission_gate(auth_context, command.permission_action, dry_run=command.dry_run)
    if not gate["allowed"]:
        emit(
            {
                "status": "blocked",
                "menu_id": menu["menu_id"],
                "expires_at": menu["expires_at"],
                "starter_role": auth_context.get("user_role"),
                "selected_command": _command_public(command),
                "execution_status": "blocked",
                "blocked_reason": gate["reason"],
                "template_id": "permission-denied",
                "auth_context": auth_context,
            }
        )
        return
    if len(tokens) < command.min_args:
        _update_menu(args.db, menu["menu_id"], status="awaiting_params", selected_command_id=command.command_id)
        emit(
            {
                "status": "awaiting_params",
                "menu_id": menu["menu_id"],
                "expires_at": menu["expires_at"],
                "starter_role": auth_context.get("user_role"),
                "selected_command": _command_public(command),
                "execution_status": "waiting_for_params",
                "blocked_reason": "missing_required_params",
                "template_id": "command-menu-params",
                "param_hint": command.usage,
                "auth_context": auth_context,
            }
        )
        return
    result = command.handler(args, tokens)
    result_summary = _safe_summary(result)
    final_reply = _render_final_reply(command, result_summary)
    output_gate = feishu_output_gate(source=args.source, content_kind="text", message=final_reply)
    _update_menu(args.db, menu["menu_id"], status="executed", selected_command_id=command.command_id)
    emit(
        {
            "status": "ok" if output_gate.get("status") == "ok" else "blocked",
            "menu_id": menu["menu_id"],
            "expires_at": menu["expires_at"],
            "starter_role": auth_context.get("user_role"),
            "available_commands": None,
            "selected_command": _command_public(command),
            "execution_status": "executed" if output_gate.get("status") == "ok" else "blocked",
            "blocked_reason": output_gate.get("blocked_reason"),
            "template_id": "command-menu-result" if output_gate.get("status") == "ok" else output_gate.get("template_id"),
            "result_summary": result_summary,
            "final_reply": final_reply if output_gate.get("status") == "ok" else None,
            "auth_context": auth_context,
        }
    )


def command_menu_cancel(args: argparse.Namespace) -> None:
    _schema(args.db)
    auth_context = _auth_context(args)
    starter_id = _starter_id(args)
    if not starter_id:
        emit(
            {
                "status": "blocked",
                "blocked_reason": "missing_menu_owner_identity",
                "template_id": "permission-denied",
                "auth_context": auth_context,
            }
        )
        return
    menu = _latest_menu_for_owner(args.db, args.chat_id, starter_id)
    if not menu:
        emit(
            {
                "status": "ok",
                "menu_id": None,
                "starter_role": auth_context.get("user_role"),
                "execution_status": "no_active_menu",
                "blocked_reason": None,
                "template_id": "command-menu-cancelled",
                "auth_context": auth_context,
            }
        )
        return
    _update_menu(args.db, menu["menu_id"], status="cancelled", selected_command_id="0")
    emit(
        {
            "status": "ok",
            "menu_id": menu["menu_id"],
            "expires_at": menu["expires_at"],
            "starter_role": menu["starter_role"],
            "execution_status": "cancelled",
            "blocked_reason": None,
            "template_id": "command-menu-cancelled",
            "auth_context": auth_context,
        }
    )
