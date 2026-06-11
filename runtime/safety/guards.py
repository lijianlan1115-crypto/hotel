from __future__ import annotations

import os
from typing import Any


def price_guard(
    *,
    old_price: float | None,
    new_price: float,
    floor_price: float | None,
    ceiling_price: float | None,
    single_change_limit_pct: float = 0.15,
) -> dict[str, Any]:
    violations: list[str] = []
    if floor_price is not None and new_price < floor_price:
        violations.append("below_floor_price")
    if ceiling_price is not None and new_price > ceiling_price:
        violations.append("above_ceiling_price")
    if old_price:
        change_pct = abs(new_price - old_price) / old_price
        if change_pct > single_change_limit_pct:
            violations.append("single_change_limit_exceeded")
    else:
        change_pct = None
    return {
        "passed": not violations,
        "violations": violations,
        "change_pct": round(change_pct, 4) if change_pct is not None else None,
        "single_change_limit_pct": single_change_limit_pct,
    }


def live_enabled(vendor: str) -> bool:
    env_key = f"{vendor.upper()}_ENABLE_LIVE"
    return os.environ.get(env_key) == "1"


def requires_approval(action_type: str) -> bool:
    return action_type in {"price_update", "quota_update", "room_quota_update", "promotion_update", "review_publish"}
