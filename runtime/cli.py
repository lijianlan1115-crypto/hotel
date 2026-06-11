from __future__ import annotations

import argparse

from runtime.adapters.beyondh import beyondh_call, build_beyondh_request
from runtime.adapters.database import DB_KINDS, INSPECT_MODES, TEMPLATES, database_inspect, database_query
from runtime.adapters.dindanll import (
    build_dindanll_request,
    normalize_dindanll_inventory_sample,
    normalize_dindanll_order_sample,
    normalize_dindanll_price_sample,
)
from runtime.adapters.meituan import build_meituan_request, normalize_meituan_price_sample, normalize_meituan_room_count_sample
from runtime.common import DEFAULT_DB, emit, parse_json_input, redacted_request, source_meta
from runtime.contracts import validate_contract
from runtime.decisions.baseline import baseline
from runtime.decisions.calendar import calendar_query, calendar_sync, event_discover, market_context
from runtime.decisions.command_menu import command_menu_cancel, command_menu_reply, command_menu_start
from runtime.decisions.competition import competition_alert
from runtime.decisions.customer import customer_analysis
from runtime.decisions.demand import demand_index, snapshot
from runtime.decisions.deviation import deviation
from runtime.decisions.ota_health import conversion_diagnosis, ota_health
from runtime.decisions.pricing import baseline_price, execute_price, expected_occupancy, revenue_decision
from runtime.decisions.promotion import promotion_execute, promotion_plan, promotion_roi
from runtime.decisions.reputation import reputation_diagnosis
from runtime.decisions.tasks import frontdesk_tasks
from runtime.safety.approvals import validate_approval_payload
from runtime.safety.auth import ACTION_TO_PERMISSION, ROLES, build_auth_context, permission_gate
from runtime.safety.feishu_output import feishu_output_gate as evaluate_feishu_output_gate
from runtime.storage import approval_create, approval_mark as storage_approval_mark, init_db, log_api, seed_demo


AUTH_SOURCES = ["feishu", "cli", "cron", "manual_test"]


def add_auth_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--auth-source", choices=AUTH_SOURCES, default="manual_test")
    parser.add_argument("--user-id")
    parser.add_argument("--open-id")
    parser.add_argument("--union-id")
    parser.add_argument("--chat-id")
    parser.add_argument("--user-role", choices=list(ROLES))
    parser.add_argument("--auth-config")


def add_menu_identity_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", choices=AUTH_SOURCES, default="feishu")
    parser.add_argument("--user-id")
    parser.add_argument("--open-id")
    parser.add_argument("--union-id")
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--user-role", choices=list(ROLES))
    parser.add_argument("--auth-config")


def auth_context_from_args(args: argparse.Namespace) -> dict:
    return build_auth_context(
        source=getattr(args, "auth_source", getattr(args, "source", "manual_test")),
        user_id=getattr(args, "user_id", None),
        open_id=getattr(args, "open_id", None),
        union_id=getattr(args, "union_id", None),
        chat_id=getattr(args, "chat_id", None),
        user_role=getattr(args, "user_role", None),
        config_path=getattr(args, "auth_config", None),
    )


def auth_check(args: argparse.Namespace) -> None:
    auth_context = auth_context_from_args(args)
    gate = permission_gate(auth_context, args.action, dry_run=args.dry_run)
    emit(
        {
            "status": "ok" if gate["allowed"] else "blocked",
            "skill": args.skill,
            "action": args.action,
            "dry_run": args.dry_run,
            "required_permission": gate["required_permission"],
            "allowed": gate["allowed"],
            "reason": gate["reason"],
            "auth_context": auth_context,
        }
    )


def approval_create_checked(args: argparse.Namespace) -> None:
    auth_context = auth_context_from_args(args)
    gate = permission_gate(auth_context, "create_approval")
    if not gate["allowed"]:
        emit({"status": "blocked", "reason": gate["reason"], "auth_context": auth_context})
        return
    payload = parse_json_input(args.payload)
    payload_gate = validate_approval_payload(payload, args.action_type)
    if not payload_gate["allowed"]:
        emit(
            {
                "status": "blocked",
                "reason": payload_gate["reason"],
                "approval_required": False,
                "template_id": payload_gate.get("template_id"),
                "auth_context": auth_context,
                "payload_gate": payload_gate,
            }
        )
        return
    approval_create(args)


def approval_mark_checked(args: argparse.Namespace) -> None:
    auth_context = auth_context_from_args(args)
    gate = permission_gate(auth_context, "approve_live_action")
    if not gate["allowed"]:
        emit({"status": "blocked", "reason": gate["reason"], "auth_context": auth_context})
        return
    storage_approval_mark(args)


def adapter_request(args: argparse.Namespace) -> None:
    biz = parse_json_input(args.biz_content, getattr(args, "biz_content_b64", None))
    adapter = args.adapter
    if adapter == "beyondh":
        if not args.method:
            emit({"status": "error", "message": "--method is required for beyondh"})
            return
        request_body = build_beyondh_request(args.method, biz)
        request = {
            "method": "POST",
            "url": "BEYONDH_BASE_URL",
            "content_type": "application/json",
            "headers": {"Content-Type": "application/json"},
            "body": request_body,
        }
        source = source_meta("beyondh", args.channel_source or "pms", "beyondh_api", "write_dry_run", "manual_required")
        method = args.method
    elif adapter == "meituan":
        if not args.path:
            emit({"status": "error", "message": "--path is required for meituan"})
            return
        request = build_meituan_request(args.path, biz, args.business_id)
        source = source_meta("meituan", args.channel_source or "meituan", "meituan_api", "write_dry_run", "manual_required")
        method = args.path
    elif adapter == "dindanll":
        if not args.path:
            emit({"status": "error", "message": "--path is required for dindanll"})
            return
        request = build_dindanll_request(args.path, biz)
        source = source_meta("dindanll", args.channel_source or "pms", "dindanll_api", "write_dry_run", "manual_required")
        method = args.path
    else:
        emit({"status": "error", "message": f"unsupported adapter: {adapter}"})
        return

    summary = {
        **source,
        "adapter": adapter,
        "request": redacted_request(request),
        "dry_run": True,
        "live_call": False,
    }
    if not args.no_log:
        log_api(args.hotel_id, method, summary, {"dry_run": True}, "dry_run", args.db)
    emit({"status": "dry_run", "summary": summary, "contract_validation": validate_contract(summary)})


def normalize_sample(args: argparse.Namespace) -> None:
    normalizers = {
        "meituan-price": normalize_meituan_price_sample,
        "meituan-room-count": normalize_meituan_room_count_sample,
        "dindanll-price": normalize_dindanll_price_sample,
        "dindanll-inventory": normalize_dindanll_inventory_sample,
        "dindanll-order": normalize_dindanll_order_sample,
    }
    payload = normalizers[args.sample]()
    emit({"status": "ok", "sample": args.sample, "payload": payload, "contract_validation": validate_contract(payload)})


def feishu_output_gate(args: argparse.Namespace) -> None:
    emit(
        evaluate_feishu_output_gate(
            source=args.source,
            content_kind=args.content_kind,
            message=args.message,
            filename=args.filename,
            artifact_kind=args.artifact_kind,
        )
    )


def env_check(args: argparse.Namespace) -> None:
    import os

    keys = [
        "HOTEL_OTA_DB",
        "HOTEL_OTA_LOG_DIR",
        "HOTEL_OTA_ENV",
        "HOTEL_OTA_AUTH_CONFIG",
        "HOTEL_OTA_DB_SOURCE_ENABLE",
        "HOTEL_OTA_DB_KIND",
        "HOTEL_OTA_DB_MAPPING_CONFIG",
        "HOTEL_OTA_DB_PROFILE",
        "HOTEL_OTA_DB_DSN",
        "HOTEL_OTA_DB_READONLY",
        "HOTEL_OTA_FEISHU_DEBUG",
        "HOTEL_OTA_FEISHU_FINAL_GATE_REQUIRED",
        "HOTEL_OTA_FEISHU_ALLOW_FILE_EXPORT",
        "HOTEL_OTA_FEISHU_ALLOW_CONFIG_EXPORT",
        "HOTEL_OTA_FEISHU_ALLOW_RAW_DATA_EXPORT",
        "BEYONDH_ENABLE_LIVE",
        "MEITUAN_ENABLE_LIVE",
        "DINDANLL_ENABLE_LIVE",
    ]
    values = {key: os.environ.get(key) for key in keys}
    missing = [key for key, value in values.items() if value in (None, "")]
    database_source_enabled = values.get("HOTEL_OTA_DB_SOURCE_ENABLE") == "1"
    live_flags = {
        "BEYONDH_ENABLE_LIVE": values.get("BEYONDH_ENABLE_LIVE"),
        "MEITUAN_ENABLE_LIVE": values.get("MEITUAN_ENABLE_LIVE"),
        "DINDANLL_ENABLE_LIVE": values.get("DINDANLL_ENABLE_LIVE"),
    }
    live_flags_explicit = all(flag not in (None, "") for flag in live_flags.values())
    live_flags_disabled = all((flag or "0") == "0" for flag in live_flags.values())
    safety_ok = (
        values.get("HOTEL_OTA_ENV", "production") == "production"
        and values.get("HOTEL_OTA_FEISHU_DEBUG", "0") == "0"
        and values.get("HOTEL_OTA_FEISHU_FINAL_GATE_REQUIRED", "1") == "1"
        and values.get("HOTEL_OTA_FEISHU_ALLOW_FILE_EXPORT", "0") == "0"
        and values.get("HOTEL_OTA_FEISHU_ALLOW_CONFIG_EXPORT", "0") == "0"
        and values.get("HOTEL_OTA_FEISHU_ALLOW_RAW_DATA_EXPORT", "0") == "0"
        and live_flags_explicit
        and live_flags_disabled
    )
    auth_config = values.get("HOTEL_OTA_AUTH_CONFIG")
    mapping_config = values.get("HOTEL_OTA_DB_MAPPING_CONFIG")
    db_path = values.get("HOTEL_OTA_DB")
    log_dir = values.get("HOTEL_OTA_LOG_DIR")
    path_status = {
        "auth_config_exists": bool(auth_config and os.path.exists(auth_config)),
        "db_mapping_config_exists": bool(mapping_config and os.path.exists(mapping_config)),
        "db_path_parent_exists": bool(db_path and os.path.exists(os.path.dirname(db_path) or ".")),
        "log_dir_exists": bool(log_dir and os.path.isdir(log_dir)),
    }
    must_fix = []
    if not safety_ok:
        must_fix.append("production_safety_env_not_locked")
    if values.get("HOTEL_OTA_FEISHU_FINAL_GATE_REQUIRED") != "1":
        must_fix.append("gateway_final_gate_requirement_not_set")
    if not live_flags_explicit:
        must_fix.append("live_execution_flags_missing")
    if not live_flags_disabled:
        must_fix.append("live_execution_enabled_before_release")
    if not path_status["auth_config_exists"]:
        must_fix.append("auth_config_missing_or_unreadable")
    if database_source_enabled:
        if values.get("HOTEL_OTA_DB_READONLY") != "1":
            must_fix.append("database_readonly_not_enforced")
        if values.get("HOTEL_OTA_DB_KIND") in {"mysql", "postgres"}:
            if not values.get("HOTEL_OTA_DB_DSN"):
                must_fix.append("database_dsn_missing")
            if not path_status["db_mapping_config_exists"]:
                must_fix.append("database_mapping_config_missing_or_unreadable")
    else:
        must_fix.append("database_source_disabled_for_commercial")
    if not path_status["db_path_parent_exists"]:
        must_fix.append("sqlite_parent_dir_missing")
    if not path_status["log_dir_exists"]:
        must_fix.append("log_dir_missing")
    commercial_blockers = [item for item in must_fix if item != "database_source_disabled_for_commercial"]
    if commercial_blockers:
        readiness_stage = "commercial_blocked"
    elif not database_source_enabled:
        readiness_stage = "internal_demo_only"
    else:
        readiness_stage = "commercial_data_ready"
    emit(
        {
            "status": "ok" if safety_ok else "warning",
            "database_source_status": "enabled" if database_source_enabled else "database_source_disabled",
            "safety_status": "production_locked" if safety_ok else "check_environment",
            "readiness_stage": readiness_stage,
            "must_fix_before_commercial": must_fix,
            "path_status": path_status,
            "live_execution_status": (
                "disabled_safe"
                if live_flags_explicit and live_flags_disabled
                else "missing_live_execution_flags"
                if not live_flags_explicit
                else "live_enabled_requires_release_approval"
            ),
            "missing_keys": missing,
            "env": {key: ("set" if value else "missing") for key, value in values.items()},
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hotel OTA OpenClaw runtime helper")
    parser.add_argument("--db", default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db").set_defaults(func=init_db)
    sub.add_parser("seed-demo").set_defaults(func=seed_demo)

    p = sub.add_parser("auth-check")
    p.add_argument("--source", choices=AUTH_SOURCES, default="manual_test")
    p.add_argument("--user-id")
    p.add_argument("--open-id")
    p.add_argument("--union-id")
    p.add_argument("--chat-id")
    p.add_argument("--user-role", choices=list(ROLES))
    p.add_argument("--auth-config")
    p.add_argument("--skill", default="unknown")
    p.add_argument("--action", choices=sorted(ACTION_TO_PERMISSION), required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=auth_check)

    p = sub.add_parser("snapshot")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--source", default="sample")
    p.set_defaults(func=snapshot)

    p = sub.add_parser("baseline")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date")
    p.set_defaults(func=baseline)

    p = sub.add_parser("deviation")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date")
    p.set_defaults(func=deviation)

    p = sub.add_parser("revenue-decision")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--channel", default="Mtop")
    p.add_argument("--begin-date")
    p.add_argument("--end-date")
    p.add_argument("--activity-discount-factors", help="Comma-separated OTA activity factors, e.g. 0.9,0.95")
    p.add_argument("--pms-price", type=float, help="PMS price reference only; never used as OTA execution target.")
    p.set_defaults(func=revenue_decision)

    p = sub.add_parser("expected-occupancy")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date")
    p.set_defaults(func=expected_occupancy)

    p = sub.add_parser("baseline-price")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date")
    p.set_defaults(func=baseline_price)

    p = sub.add_parser("demand-index")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date")
    p.set_defaults(func=demand_index)

    p = sub.add_parser("calendar-sync")
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--seed-file")
    p.set_defaults(func=calendar_sync)

    p = sub.add_parser("calendar-query")
    p.add_argument("--date", required=True)
    p.set_defaults(func=calendar_query)

    p = sub.add_parser("market-context")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date")
    p.add_argument(
        "--weather-provider",
        default="weather_mcp",
        choices=["weather_mcp", "wttr_http", "weather_fixture", "amap_api", "qweather_api", "manual_weather", "manual", "sample", "wttr_mcp"],
    )
    p.add_argument("--weather-fixture")
    p.add_argument("--operating-fixture")
    p.add_argument("--progress-fixture")
    p.set_defaults(func=market_context)

    p = sub.add_parser("event-discover")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date-range", required=True)
    p.add_argument("--fixture-file")
    p.set_defaults(func=event_discover)

    p = sub.add_parser("ota-health")
    p.add_argument("--hotel-id", required=True)
    p.set_defaults(func=ota_health)

    p = sub.add_parser("conversion-diagnosis")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--debug", action="store_true")
    p.set_defaults(func=conversion_diagnosis)

    p = sub.add_parser("competition-alert")
    p.add_argument("--hotel-id", required=True)
    p.set_defaults(func=competition_alert)

    p = sub.add_parser("frontdesk-tasks")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date")
    p.set_defaults(func=frontdesk_tasks)

    p = sub.add_parser("customer-analysis")
    p.add_argument("--hotel-id", required=True)
    p.set_defaults(func=customer_analysis)

    p = sub.add_parser("reputation-diagnosis")
    p.add_argument("--hotel-id", required=True)
    p.set_defaults(func=reputation_diagnosis)

    p = sub.add_parser("promotion-plan")
    p.add_argument("--hotel-id", required=True)
    p.set_defaults(func=promotion_plan)

    p = sub.add_parser("promotion-roi")
    p.add_argument("--hotel-id", required=True)
    p.set_defaults(func=promotion_roi)

    p = sub.add_parser("promotion-execute")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--approval-id")
    p.add_argument("--approved-by")
    p.add_argument("--approver-role", choices=["admin", "owner", "operator", "frontdesk", "guest"])
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--live", dest="dry_run", action="store_false")
    add_auth_args(p)
    p.set_defaults(func=promotion_execute)

    p = sub.add_parser("beyondh-call")
    p.add_argument("--hotel-id")
    p.add_argument("--method", required=True)
    p.add_argument("--biz-content", default="{}")
    p.add_argument("--biz-content-b64")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-log", action="store_true")
    p.add_argument("--timeout", type=int, default=20)
    p.set_defaults(func=beyondh_call)

    p = sub.add_parser("adapter-request")
    p.add_argument("--hotel-id")
    p.add_argument("--adapter", choices=["beyondh", "meituan", "dindanll"], required=True)
    p.add_argument("--method")
    p.add_argument("--path")
    p.add_argument("--biz-content", default="{}")
    p.add_argument("--biz-content-b64")
    p.add_argument("--business-id", type=int, default=57)
    p.add_argument("--channel-source")
    p.add_argument("--no-log", action="store_true")
    p.set_defaults(func=adapter_request)

    p = sub.add_parser("database-query")
    p.add_argument("--db-kind", choices=list(DB_KINDS), required=True)
    p.add_argument("--template", choices=list(TEMPLATES), required=True)
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date")
    p.add_argument("--profile")
    p.add_argument("--mapping-config")
    p.add_argument("--dsn")
    p.add_argument("--sql", help="Rejected by design. Use --template instead.")
    p.set_defaults(func=database_query)

    p = sub.add_parser("database-inspect")
    p.add_argument("--db-kind", choices=list(DB_KINDS), required=True)
    p.add_argument("--mode", choices=list(INSPECT_MODES), required=True)
    p.add_argument("--profile")
    p.add_argument("--mapping-config")
    p.add_argument("--dsn")
    p.add_argument("--table")
    p.add_argument("--limit", type=int, default=5)
    p.set_defaults(func=database_inspect)

    p = sub.add_parser("normalize-sample")
    p.add_argument(
        "--sample",
        choices=["meituan-price", "meituan-room-count", "dindanll-price", "dindanll-inventory", "dindanll-order"],
        required=True,
    )
    p.set_defaults(func=normalize_sample)

    p = sub.add_parser("feishu-output-gate")
    p.add_argument("--source", default="feishu")
    p.add_argument("--content-kind", choices=["text", "file", "artifact"], default="text")
    p.add_argument("--message", default="")
    p.add_argument("--filename")
    p.add_argument("--artifact-kind")
    p.set_defaults(func=feishu_output_gate)

    p = sub.add_parser("command-menu-start")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--message", default="菜单")
    add_menu_identity_args(p)
    p.set_defaults(func=command_menu_start)

    p = sub.add_parser("command-menu-reply")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--reply", required=True)
    add_menu_identity_args(p)
    p.set_defaults(func=command_menu_reply)

    p = sub.add_parser("command-menu-cancel")
    add_menu_identity_args(p)
    p.set_defaults(func=command_menu_cancel)

    p = sub.add_parser("env-check")
    p.set_defaults(func=env_check)

    p = sub.add_parser("execute-price")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--room-type-id", required=True)
    p.add_argument("--channel", default="Mtop")
    p.add_argument("--normal-price", type=float, required=True)
    p.add_argument("--weekend-price", type=float)
    p.add_argument("--begin-date", required=True)
    p.add_argument("--end-date", required=True)
    p.add_argument("--approved-by")
    p.add_argument("--approval-id")
    p.add_argument("--approver-role", choices=["admin", "owner", "operator", "frontdesk", "guest"])
    p.add_argument("--old-price", type=float)
    p.add_argument("--floor-price", type=float)
    p.add_argument("--ceiling-price", type=float)
    p.add_argument("--activity-discount-factors", help="Comma-separated OTA activity factors, e.g. 0.9,0.95")
    p.add_argument("--pms-price", type=float, help="PMS price reference only; never used as OTA execution target.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-log", action="store_true")
    p.add_argument("--timeout", type=int, default=20)
    add_auth_args(p)
    p.set_defaults(func=execute_price)

    p = sub.add_parser("approval-create")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--action-type", required=True)
    p.add_argument("--requested-by", required=True)
    p.add_argument("--payload", required=True)
    add_auth_args(p)
    p.set_defaults(func=approval_create_checked)

    p = sub.add_parser("approval-mark")
    p.add_argument("--approval-id", required=True)
    p.add_argument("--user", required=True)
    add_auth_args(p)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--approve", action="store_true")
    group.add_argument("--reject", action="store_true")
    p.set_defaults(func=approval_mark_checked)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except Exception as exc:
        emit({"status": "error", "error": type(exc).__name__, "message": str(exc)})
        return 1
