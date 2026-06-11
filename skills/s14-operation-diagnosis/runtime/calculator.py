"""S14 scoring formulas.

All module formulas used by the OpenClaw S14 skill live in this file. Do not
hard-code S14 formulas in SKILL.md, prompt text, or data_fetcher.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MODULE_DEFS: dict[str, tuple[str, float]] = {
    "M01": ("经营结果与收益锚点", 20),
    "M02": ("流量曝光与竞争圈", 15),
    "M03": ("转化下单与路径断点", 15),
    "M04": ("价格收益与房态库存", 15),
    "M05": ("推广效率与 ROI", 10),
    "M06": ("页面展示与入口基础", 10),
    "M07": ("口碑信任与服务响应", 8),
    "M08": ("执行复盘与数据完整度", 7),
}


@dataclass
class ScoreResult:
    module_id: str
    name: str
    score: float
    weight: float
    confidence: str
    reasons: list[str]


def _num(metrics: dict[str, Any], key: str, default: float = 0) -> float:
    value = metrics.get(key, default)
    if value in (None, "", "null", "None", "--", "-"):
        return default
    if isinstance(value, str) and value.endswith("%"):
        try:
            return float(value[:-1]) / 100
        except ValueError:
            return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0, high: float = 1) -> float:
    return max(low, min(high, value))


def _ratio(value: float, target: float, higher_is_better: bool = True) -> float:
    if target <= 0:
        return 0
    raw = value / target if higher_is_better else target / max(value, 0.000001)
    return _clamp(raw)


def _enum_score(value: Any, mapping: dict[str, float], default: float = 0.4) -> float:
    return mapping.get(str(value or "unknown"), default)


def calculate_module_score(module_id: str, metrics: dict[str, Any]) -> ScoreResult:
    """Calculate one S14 module score.

    Args:
        module_id: One of M01-M08.
        metrics: Normalized business metrics from data_fetcher.py.

    Returns:
        ScoreResult with score already capped by the module weight.
    """
    calculators = {
        "M01": _calculate_m01,
        "M02": _calculate_m02,
        "M03": _calculate_m03,
        "M04": _calculate_m04,
        "M05": _calculate_m05,
        "M06": _calculate_m06,
        "M07": _calculate_m07,
        "M08": _calculate_m08,
    }
    if module_id not in calculators:
        raise ValueError(f"unsupported module_id: {module_id}")
    score, reasons = calculators[module_id](metrics)
    name, weight = MODULE_DEFS[module_id]
    score = round(min(max(score, 0), weight), 2)
    completeness = _num(metrics, "field_completeness", 1)
    confidence = "high" if completeness >= 0.8 else "medium" if completeness >= 0.55 else "low"
    return ScoreResult(module_id, name, score, weight, confidence, reasons)


def calculate_all_modules(metrics: dict[str, Any]) -> list[ScoreResult]:
    return [calculate_module_score(module_id, metrics) for module_id in MODULE_DEFS]


def _calculate_m01(metrics: dict[str, Any]) -> tuple[float, list[str]]:
    revpar = _num(metrics, "revpar")
    adr = _num(metrics, "adr")
    occupancy = _num(metrics, "occupancy")
    score = (
        _ratio(revpar, 200) * 0.4
        + _ratio(adr, 150) * 0.3
        + _ratio(occupancy, 0.85) * 0.3
    ) * 20
    return score, [f"RevPAR={revpar:.2f}", f"ADR={adr:.2f}", f"出租率={occupancy:.2%}"]


def _calculate_m02(metrics: dict[str, Any]) -> tuple[float, list[str]]:
    exposure = _num(metrics, "exposure")
    views = _num(metrics, "views")
    peer_rank = _num(metrics, "peer_rank", 0.5)
    score = (
        _ratio(exposure, 10000) * 0.45
        + _ratio(views, 1200) * 0.35
        + _ratio(peer_rank, 0.3, higher_is_better=False) * 0.2
    ) * 15
    return score, [f"曝光={exposure:.0f}", f"浏览={views:.0f}", f"竞争排名分位={peer_rank:.2f}"]


def _calculate_m03(metrics: dict[str, Any]) -> tuple[float, list[str]]:
    booking = _num(metrics, "booking_conversion_rate")
    payment = _num(metrics, "payment_conversion_rate")
    lost_orders = _num(metrics, "lost_orders")
    score = (
        _ratio(booking, 0.08) * 0.4
        + _ratio(payment, 0.035) * 0.4
        + _ratio(lost_orders, 5, higher_is_better=False) * 0.2
    ) * 15
    return score, [f"浏览转化={booking:.2%}", f"支付转化={payment:.2%}", f"流失订单={lost_orders:.0f}"]


def _calculate_m04(metrics: dict[str, Any]) -> tuple[float, list[str]]:
    price_completeness = _num(metrics, "price_completeness", 0.5)
    inventory_health = _num(metrics, "inventory_health_rate", 0.5)
    room_type_health = _num(metrics, "room_type_health_rate", 0.5)
    score = (price_completeness * 0.35 + inventory_health * 0.35 + room_type_health * 0.3) * 15
    return score, [f"价格完整度={price_completeness:.2%}", f"库存健康率={inventory_health:.2%}", f"房型健康率={room_type_health:.2%}"]


def _calculate_m05(metrics: dict[str, Any]) -> tuple[float, list[str]]:
    promo_amount = _num(metrics, "promo_amount")
    promo_cost = _num(metrics, "promo_cost")
    roi = _num(metrics, "promo_roi", promo_amount / promo_cost if promo_cost else 0)
    cost_rate = promo_cost / promo_amount if promo_amount else 1
    score = (
        _ratio(roi, 5) * 0.5
        + _ratio(promo_amount, 10000) * 0.3
        + _ratio(cost_rate, 0.18, higher_is_better=False) * 0.2
    ) * 10
    return score, [f"推广金额={promo_amount:.2f}", f"推广花费={promo_cost:.2f}", f"ROI={roi:.2f}"]


def _calculate_m06(metrics: dict[str, Any]) -> tuple[float, list[str]]:
    image = _enum_score(metrics.get("image_quality_rating"), {"good": 1, "average": 0.65, "poor": 0.25, "unknown": 0.35})
    video = _enum_score(metrics.get("video_status"), {"complete": 1, "partial": 0.6, "missing": 0.2, "unknown": 0.35})
    selling = _enum_score(metrics.get("room_selling_point_status"), {"complete": 1, "partial": 0.6, "poor": 0.25, "unknown": 0.35})
    tag = _enum_score(metrics.get("entry_tag_quality"), {"complete": 1, "partial": 0.6, "poor": 0.25, "unknown": 0.35})
    score = (image * 0.35 + video * 0.2 + selling * 0.25 + tag * 0.2) * 10
    return score, [
        f"图片={metrics.get('image_quality_rating', 'unknown')}",
        f"视频={metrics.get('video_status', 'unknown')}",
        f"卖点={metrics.get('room_selling_point_status', 'unknown')}",
        f"入口标签={metrics.get('entry_tag_quality', 'unknown')}",
    ]


def _calculate_m07(metrics: dict[str, Any]) -> tuple[float, list[str]]:
    rating = _num(metrics, "rating_total", 4.0)
    bad_rate = _num(metrics, "bad_review_rate", 0.08)
    unreplied = _num(metrics, "unreplied_reviews")
    score = (
        _ratio(rating, 4.8) * 0.5
        + _ratio(bad_rate, 0.03, higher_is_better=False) * 0.25
        + _ratio(unreplied, 1, higher_is_better=False) * 0.25
    ) * 8
    return score, [f"评分={rating:.2f}", f"差评率={bad_rate:.2%}", f"未回复评价={unreplied:.0f}"]


def _calculate_m08(metrics: dict[str, Any]) -> tuple[float, list[str]]:
    completeness = _num(metrics, "field_completeness", 0.5)
    has_actions = 1.0 if metrics.get("completed_actions") and metrics.get("pending_actions") else 0.35
    has_review = 1.0 if metrics.get("review_reason") else 0.35
    score = (completeness * 0.45 + has_actions * 0.3 + has_review * 0.25) * 7
    return score, [f"字段完整度={completeness:.2%}", f"整改动作={'有' if has_actions == 1 else '不足'}", f"复盘原因={'有' if has_review == 1 else '不足'}"]


def apply_cap_rules(module_scores: list[ScoreResult | dict[str, Any]], metrics: dict[str, Any]) -> tuple[float, list[str]]:
    """Apply total-score cap rules and return final_score, caps."""
    def value(item: ScoreResult | dict[str, Any], key: str, default: Any = None) -> Any:
        return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)

    total_score = sum(float(value(item, "score", 0)) for item in module_scores)
    caps: list[str] = []

    if _num(metrics, "field_completeness", 1) < 0.7:
        total_score = min(total_score, 70)
        caps.append("C07 数据可信度封顶：关键经营字段缺失超过30%，总分最高70。")
    if not metrics.get("available_room_nights"):
        total_score = min(total_score, 85)
        caps.append("C01 可售间夜封顶：缺 available_room_nights 且无法推导，总分最高85。")
    m03 = next((item for item in module_scores if value(item, "module_id") == "M03"), None)
    if m03 and float(value(m03, "score", 0)) / 15 < 0.6:
        total_score = min(total_score, 78)
        caps.append("C03 转化封顶：转化下单模块低于60%，总分最高78。")
    if _num(metrics, "promo_cost") > 0 and not metrics.get("promo_detail_ready", False):
        total_score = min(total_score, 88)
        caps.append("C05 推广封顶：有推广花费但缺曝光/点击/CPC/成交明细，总分最高88。")

    return round(total_score, 2), caps
