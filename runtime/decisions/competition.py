from __future__ import annotations

import argparse

from runtime.common import emit
from runtime.contracts import standard_envelope


def competition_alert(args: argparse.Namespace) -> None:
    competitors = [
        {"competitor_name": "同商圈电竞酒店A", "price": 148, "rank": 3, "activity": "满减", "delta_to_ours": -11},
        {"competitor_name": "同档次酒店B", "price": 168, "rank": 1, "activity": "会员价", "delta_to_ours": 9},
    ]
    emit(
        standard_envelope(
            status="ok",
            skill_id="S7",
            summary="竞对有局部低价，但不建议盲目跟降，先判断对方体量、活动和销量排名。",
            evidence={"competitors": competitors},
            recommendations=["竞对降价只触发预警，不直接触发自动调价。", "如本店进度落后，再交 S5 做收益建议。"],
            actions=[{"type": "alert", "warning_level": "watch", "next_skill": "S5"}],
            risk_level="medium",
        )
    )
