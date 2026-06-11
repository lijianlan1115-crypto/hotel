from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ROLES = ("admin", "owner", "operator", "frontdesk", "guest")

PERMISSIONS_BY_ROLE: dict[str, set[str]] = {
    "admin": {
        "view_diagnosis",
        "view_frontdesk_task",
        "run_recommendation",
        "create_dry_run",
        "create_approval",
        "approve_live_action",
        "execute_live_action",
        "manage_roles",
        "manage_safety_config",
    },
    "owner": {
        "view_diagnosis",
        "view_frontdesk_task",
        "run_recommendation",
        "create_dry_run",
        "create_approval",
        "approve_live_action",
        "execute_live_action",
        "manage_safety_config",
    },
    "operator": {
        "view_diagnosis",
        "view_frontdesk_task",
        "run_recommendation",
        "create_dry_run",
        "create_approval",
    },
    "frontdesk": {"view_frontdesk_task"},
    "guest": set(),
}

ACTION_TO_PERMISSION = {
    "view_diagnosis": "view_diagnosis",
    "view_frontdesk_task": "view_frontdesk_task",
    "run_recommendation": "run_recommendation",
    "create_dry_run": "create_dry_run",
    "create_approval": "create_approval",
    "approve_live_action": "approve_live_action",
    "execute_live_action": "execute_live_action",
    "manage_roles": "manage_roles",
    "manage_safety_config": "manage_safety_config",
    "price_update": "execute_live_action",
    "quota_update": "execute_live_action",
    "room_quota_update": "execute_live_action",
    "promotion_update": "execute_live_action",
    "review_publish": "execute_live_action",
}

WRITE_ACTIONS = {"price_update", "quota_update", "room_quota_update", "promotion_update", "review_publish"}


def load_auth_config(config_path: str | None = None) -> dict[str, Any]:
    path = config_path or os.environ.get("HOTEL_OTA_AUTH_CONFIG")
    if not path:
        return {"users": [], "allowed_chat_ids": [], "config_source": "missing"}
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {"users": [], "allowed_chat_ids": [], "config_source": path, "load_error": "file_not_found"}
    except json.JSONDecodeError as exc:
        return {"users": [], "allowed_chat_ids": [], "config_source": path, "load_error": f"invalid_json:{exc.msg}"}
    data["config_source"] = path
    return data


def permissions_for_role(role: str | None) -> list[str]:
    return sorted(PERMISSIONS_BY_ROLE.get(role or "guest", set()))


def _value_matches(user: dict[str, Any], keys: tuple[str, ...], value: str | None) -> bool:
    if not value:
        return False
    return any(str(user.get(key, "")) == value for key in keys if user.get(key))


def _role_match_from_feishu_user(config: dict[str, Any], user_id: str | None, open_id: str | None, union_id: str | None) -> dict[str, Any] | None:
    for user in config.get("users", []):
        if _value_matches(user, ("feishu_user_id", "user_id"), user_id):
            return {"role": user.get("role"), "matched_by": "user_id", "matched_role_name": user.get("name")}
        if _value_matches(user, ("feishu_open_id", "open_id"), open_id):
            return {"role": user.get("role"), "matched_by": "open_id", "matched_role_name": user.get("name")}
        if user_id and user_id.startswith("ou_") and _value_matches(user, ("feishu_open_id", "open_id"), user_id):
            return {
                "role": user.get("role"),
                "matched_by": "open_id_fallback_from_user_id",
                "matched_role_name": user.get("name"),
                "identity_warning": "Received an ou_ Open ID through --user-id. Prefer --open-id for Feishu open_id values.",
            }
        if _value_matches(user, ("feishu_union_id", "union_id"), union_id):
            return {"role": user.get("role"), "matched_by": "union_id", "matched_role_name": user.get("name")}
    return None


def build_auth_context(
    *,
    source: str = "manual_test",
    user_id: str | None = None,
    open_id: str | None = None,
    union_id: str | None = None,
    chat_id: str | None = None,
    user_role: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    source = source or "manual_test"
    reason = "authorized"
    auth_status = "authorized"
    matched_by = None
    matched_role_name = None
    identity_warning = None

    if source == "feishu":
        config = load_auth_config(config_path)
        if config.get("load_error"):
            role = "guest"
            auth_status = "unauthorized"
            reason = config["load_error"]
        else:
            allowed_chat_ids = set(config.get("allowed_chat_ids") or config.get("groupAllowFrom") or [])
            if allowed_chat_ids and chat_id not in allowed_chat_ids:
                role = "guest"
                auth_status = "unauthorized"
                reason = "chat_not_allowed"
            elif not (user_id or open_id or union_id):
                role = "guest"
                auth_status = "missing_identity"
                reason = "missing_feishu_identity"
            else:
                match = _role_match_from_feishu_user(config, user_id, open_id, union_id)
                role = (match or {}).get("role") or "guest"
                matched_by = (match or {}).get("matched_by")
                matched_role_name = (match or {}).get("matched_role_name")
                identity_warning = (match or {}).get("identity_warning")
                if role == "guest":
                    auth_status = "unauthorized"
                    reason = "user_not_in_role_map"
    else:
        role = user_role if user_role in ROLES else "operator"
        if role == "guest":
            auth_status = "unauthorized"
            reason = "guest_role"

    if role not in ROLES:
        role = "guest"
        auth_status = "unauthorized"
        reason = "invalid_role"

    return {
        "source": source,
        "auth_status": auth_status,
        "reason": reason,
        "user_role": role,
        "matched_by": matched_by,
        "matched_role_name": matched_role_name,
        "identity_warning": identity_warning,
        "feishu_user_id": user_id,
        "feishu_open_id": open_id,
        "feishu_union_id": union_id,
        "feishu_chat_id": chat_id,
        "permissions": permissions_for_role(role),
    }


def required_permission(action: str, *, dry_run: bool = False) -> str:
    if dry_run and action in WRITE_ACTIONS:
        return "create_dry_run"
    return ACTION_TO_PERMISSION.get(action, action)


def permission_gate(auth_context: dict[str, Any], action: str, *, dry_run: bool = False) -> dict[str, Any]:
    permission = required_permission(action, dry_run=dry_run)
    permissions = set(auth_context.get("permissions", []))
    allowed = auth_context.get("auth_status") == "authorized" and permission in permissions
    return {
        "allowed": allowed,
        "required_permission": permission,
        "reason": "allowed" if allowed else f"permission_denied:{permission}",
        "auth_context": auth_context,
    }
