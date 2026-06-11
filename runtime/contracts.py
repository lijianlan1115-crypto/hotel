from __future__ import annotations

from typing import Any


CONTRACT_META_FIELDS = [
    "adapter_vendor",
    "channel_source",
    "data_source_type",
    "source_capability",
    "field_quality",
    "captured_at",
]

OUTPUT_FIELDS = [
    "status",
    "skill_id",
    "summary",
    "evidence",
    "recommendations",
    "actions",
    "risk_level",
    "approval_required",
    "next_run_at",
    "artifacts",
]


FRESHNESS_FIELDS = [
    "data_business_date",
    "data_snapshot_time",
    "freshness_status",
    "data_age_hours",
    "business_status",
    "today_label_allowed",
]


def validate_contract(payload: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in CONTRACT_META_FIELDS if key not in payload]
    return {"valid": not missing, "missing_fields": missing}


def demand_level(score: float | int | None) -> str:
    if score is None:
        return "unknown"
    if score <= 25:
        return "low"
    if score <= 50:
        return "flat"
    if score <= 75:
        return "strong"
    return "burst"


def ota_health_level(score: float | int | None) -> str:
    if score is None:
        return "unknown"
    if score >= 5:
        return "excellent"
    if score >= 4:
        return "healthy"
    if score >= 3:
        return "watch"
    if score >= 2:
        return "warning"
    return "critical"


def action_strength_label(strength: int | None) -> str:
    labels = {
        0: "no_action",
        1: "observe",
        2: "minor_adjustment",
        3: "clear_adjustment",
        4: "strong_intervention",
    }
    return labels.get(strength if strength is not None else -1, "unknown")


def _extract_freshness(evidence: dict[str, Any] | list[Any] | None) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        return {}
    return {field: evidence.get(field) for field in FRESHNESS_FIELDS if field in evidence}


def standard_envelope(
    *,
    status: str,
    skill_id: str,
    summary: str,
    evidence: dict[str, Any] | list[Any] | None = None,
    recommendations: list[str] | None = None,
    actions: list[dict[str, Any]] | None = None,
    risk_level: str = "low",
    approval_required: bool = False,
    next_run_at: str | None = None,
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = {
        "status": status,
        "skill_id": skill_id,
        "summary": summary,
        "evidence": evidence or {},
        "recommendations": recommendations or [],
        "actions": actions or [],
        "risk_level": risk_level,
        "approval_required": approval_required,
        "next_run_at": next_run_at,
        "artifacts": artifacts or [],
    }
    payload.update(_extract_freshness(evidence))
    if "today_label_allowed" not in payload:
        payload["today_label_allowed"] = payload.get("freshness_status") == "fresh"
    return payload
