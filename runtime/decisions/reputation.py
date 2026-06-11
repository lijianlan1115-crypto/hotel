from __future__ import annotations

import argparse

from runtime.common import emit
from runtime.contracts import standard_envelope


def reputation_diagnosis(args: argparse.Namespace) -> None:
    review = {
        "sentiment": "negative",
        "issue_tags": ["noise", "service_response"],
        "severity": "medium",
        "needs_manager_escalation": True,
        "needs_private_message": True,
    }
    emit(
        standard_envelope(
            status="ok",
            skill_id="S12/S13",
            summary="该评论属于中等严重差评，建议升级店长并生成回复草稿，不自动发布。",
            evidence={"review": review},
            recommendations=["先内部跟进问题，再公开回复。", "涉及补偿必须人工确认。"],
            actions=[
                {"type": "manager_escalation", "owner": "店长"},
                {"type": "reply_draft", "content": "非常抱歉影响您的入住体验，我们已安排店长复盘并跟进整改。"},
            ],
            risk_level="medium",
            approval_required=True,
        )
    )
