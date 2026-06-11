from __future__ import annotations

import argparse

from runtime.common import emit
from runtime.contracts import standard_envelope
from runtime.safety.approvals import approval_gate
from runtime.safety.auth import build_auth_context, permission_gate


def promotion_plan(args: argparse.Namespace) -> None:
    emit(
        standard_envelope(
            status="ok",
            skill_id="S8",
            summary="当前建议优先做标签型/内容型活动，价格型活动需校验底价和叠加风险。",
            evidence={"api_status": "reference_only"},
            recommendations=["先做转化，再做流量。", "活动叠加后的到手价不得低于房型底价。"],
            actions=[{"type": "promotion_dry_run", "activity_type": "label_or_content", "approval_required": True}],
            risk_level="medium",
            approval_required=True,
        )
    )


def promotion_roi(args: argparse.Namespace) -> None:
    emit(
        standard_envelope(
            status="ok",
            skill_id="S10",
            summary="推广 ROI 目前只能 dry-run 估算，余额、消耗、成交贡献字段待 API 或后台导出确认。",
            evidence={"api_status": "reference_only"},
            recommendations=["低转化时不要先加预算，先排查内容和价格一致性。"],
            actions=[{"type": "roi_decision", "decision": "observe"}],
            risk_level="medium",
        )
    )


def promotion_execute(args: argparse.Namespace) -> None:
    auth_context = build_auth_context(
        source=getattr(args, "auth_source", "manual_test"),
        user_id=getattr(args, "user_id", None),
        open_id=getattr(args, "open_id", None),
        union_id=getattr(args, "union_id", None),
        chat_id=getattr(args, "chat_id", None),
        user_role=getattr(args, "user_role", None),
        config_path=getattr(args, "auth_config", None),
    )
    permission = permission_gate(auth_context, "promotion_update", dry_run=args.dry_run)
    if not permission["allowed"]:
        emit(
            standard_envelope(
                status="blocked",
                skill_id="S11",
                summary="当前用户没有推广执行权限。",
                evidence={
                    "reason": permission["reason"],
                    "required_permission": permission["required_permission"],
                    "auth_context": auth_context,
                },
                risk_level="high",
                approval_required=True,
            )
        )
        return
    approval = approval_gate(
        approved_by=getattr(args, "approved_by", None),
        dry_run=args.dry_run,
        action_type="promotion_update",
        approval_id=getattr(args, "approval_id", None),
        approver_role=getattr(args, "approver_role", None),
    )
    if not approval["allowed"]:
        emit(
            standard_envelope(
                status="blocked",
                skill_id="S11",
                summary="推广真实执行缺少有效审批。",
                evidence={"reason": approval["reason"], "auth_context": auth_context},
                risk_level="high",
                approval_required=True,
            )
        )
        return
    if not args.dry_run:
        emit(
            standard_envelope(
                status="blocked",
                skill_id="S11",
                summary="推广 live API 尚未确认，当前不允许真实执行。",
                evidence={"api_status": "unconfirmed", "auth_context": auth_context},
                recommendations=["先保留 dry-run 和人工审批记录，待美团/OTA 推广 API 权限确认后再启用 live。"],
                risk_level="high",
                approval_required=True,
            )
        )
        return
    emit(
        standard_envelope(
            status="dry_run",
            skill_id="S11",
            summary="推广执行仅生成 dry-run 任务，不做真实渠道写入。",
            evidence={"approval_required": True, "api_status": "unconfirmed", "auth_context": auth_context},
            recommendations=["真实预算、出价、活动变更必须 admin/owner 审批。"],
            actions=[{"type": "promotion_execution_task", "status": "pending_approval"}],
            risk_level="high",
            approval_required=True,
        )
    )
