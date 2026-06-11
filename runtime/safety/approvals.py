from __future__ import annotations

from typing import Any


REQUIRED_APPROVAL_PAYLOAD_FIELDS = (
    "dry_run_summary",
    "data_business_date",
    "data_snapshot_time",
    "freshness_status",
)

MANUAL_AUDIT_FIELDS = ("recorded_by", "recorded_at", "source", "audit_summary")


def validate_approval_payload(payload: dict[str, Any], action_type: str) -> dict[str, Any]:
    missing = [field for field in REQUIRED_APPROVAL_PAYLOAD_FIELDS if not payload.get(field)]
    if missing:
        return {
            "allowed": False,
            "reason": "approval_payload_missing_required_fields",
            "missing_fields": missing,
            "template_id": "approval-request",
        }

    freshness_status = str(payload.get("freshness_status") or "")
    if freshness_status != "fresh":
        template_id = "demo-data" if freshness_status == "demo_data" else "stale-data"
        return {
            "allowed": False,
            "reason": "approval_requires_fresh_data",
            "freshness_status": freshness_status,
            "template_id": template_id,
        }

    if payload.get("business_status") not in (None, "current"):
        return {
            "allowed": False,
            "reason": "approval_requires_current_business_status",
            "business_status": payload.get("business_status"),
            "template_id": "stale-data",
        }

    if payload.get("data_source_type") == "sample_data" or "demo_data" in set(payload.get("risk_flags") or []):
        return {
            "allowed": False,
            "reason": "approval_not_allowed_for_sample_or_demo_data",
            "template_id": "demo-data",
        }

    data_source_type = str(payload.get("data_source_type") or "")
    if data_source_type in {"manual_chat", "chat", "chat_message", "manual"}:
        return {
            "allowed": False,
            "reason": "approval_not_allowed_for_manual_chat",
            "data_source_type": data_source_type,
            "template_id": "approval-bypass-refusal",
        }

    if data_source_type in {"manual_upload", "manual_entry"}:
        audit = payload.get("manual_audit") or payload.get("manual_entry_audit") or {}
        missing_audit_fields = [field for field in MANUAL_AUDIT_FIELDS if not audit.get(field)]
        if missing_audit_fields:
            return {
                "allowed": False,
                "reason": "approval_manual_entry_missing_audit_fields",
                "missing_fields": missing_audit_fields,
                "template_id": "approval-bypass-refusal",
            }

    return {"allowed": True, "reason": "approval_payload_valid", "action_type": action_type}


def approval_gate(
    *,
    approved_by: str | None,
    dry_run: bool,
    action_type: str,
    approval_id: str | None = None,
    approver_role: str | None = None,
) -> dict[str, Any]:
    if dry_run:
        return {"allowed": True, "approval_required": True, "reason": "dry_run_preview_only"}
    if not approval_id:
        return {"allowed": False, "approval_required": True, "reason": f"{action_type} requires approval_id"}
    if not approved_by:
        return {"allowed": False, "approval_required": True, "reason": f"{action_type} requires approved_by"}
    if approver_role not in {"admin", "owner"}:
        return {
            "allowed": False,
            "approval_required": True,
            "reason": f"{action_type} requires admin_or_owner_approval",
            "approver_role": approver_role or "missing",
        }
    return {"allowed": True, "approval_required": False, "reason": "approved"}
