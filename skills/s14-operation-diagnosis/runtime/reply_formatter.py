"""Strict JSON-to-Feishu formatter for S14.

The Agent may produce diagnostic JSON, but it must not produce the final
Feishu text. This module is the single source of truth for the S14 Feishu
reply. The template is locked here and exported as ``FEISHU_TEMPLATE`` so
that tests and the entry service can assert the exact byte-for-byte format.
"""

from __future__ import annotations

import json
import re
from typing import Any


FORMAT_ERROR_TEXT = "诊断结果格式异常，请重新生成。"

REQUIRED_FIELDS = (
    "hotel_name",
    "period_start",
    "period_end",
    "final_score",
    "report_url",
)

# 飞书固定模板：Bot/Agent 禁止改写。
# 报告链接必须和 URL 在同一行，避免飞书把 URL 拆成普通文本而不能点击。
FEISHU_TEMPLATE = (
    "【S14 酒店 OTA 诊断报告已生成】\n"
    "\n"
    "酒店：{hotel_name}\n"
    "周期：{period_start} 至 {period_end}\n"
    "综合得分：{final_score_int} / 100\n"
    "风险等级：{risk_text}\n"
    "报告链接：{report_url}\n"
    "说明：当前为 S14 测试机器人返回结果，不影响正式酒店 OTA Agent。"
)

_ALLOWED_RISK_LABELS = {"高风险", "中风险", "低风险"}


def risk_label(score: float) -> str:
    if score < 60:
        return "高风险"
    if score < 80:
        return "中风险"
    return "低风险"


def _normalize_required_field(value: Any) -> str:
    """Required field must be a non-empty scalar string. Reject list/dict."""

    if isinstance(value, (list, dict, tuple, set)):
        raise ValueError("S14 required field must be a scalar string")
    if value is None:
        raise ValueError("S14 required field cannot be None")
    text = str(value).strip()
    if not text:
        raise ValueError("S14 required field cannot be empty")
    return text


def _normalize_score(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("S14 final_score must be a number, not bool")
    if not isinstance(value, (int, float)):
        raise ValueError("S14 final_score must be a number")
    score = float(value)
    if score < 0 or score > 100:
        raise ValueError("S14 final_score must be in [0, 100]")
    return score


def _validate_data(data: Any) -> dict[str, Any]:
    """Validate the agent JSON dict and return normalized values."""

    if not isinstance(data, dict):
        raise ValueError("S14 Agent output must be a JSON object")

    missing = [
        field for field in REQUIRED_FIELDS
        if data.get(field) in (None, "", [], {})
    ]
    if missing:
        raise ValueError(f"S14 JSON missing required fields: {', '.join(missing)}")

    hotel_name = _normalize_required_field(data["hotel_name"])
    period_start = _normalize_required_field(data["period_start"])
    period_end = _normalize_required_field(data["period_end"])
    report_url = _normalize_required_field(data["report_url"])

    # 周期必须是 YYYY-MM-DD
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    if not date_pattern.match(period_start):
        raise ValueError("S14 period_start must be YYYY-MM-DD")
    if not date_pattern.match(period_end):
        raise ValueError("S14 period_end must be YYYY-MM-DD")

    score = _normalize_score(data["final_score"])

    # 强制以分数计算风险等级，忽略任何 Agent 传进来的 risk_text。
    risk_text = risk_label(score)
    if risk_text not in _ALLOWED_RISK_LABELS:
        raise ValueError(f"S14 risk_text must be one of {_ALLOWED_RISK_LABELS}")

    return {
        "hotel_name": hotel_name,
        "period_start": period_start,
        "period_end": period_end,
        "report_url": report_url,
        "final_score": score,
        "risk_text": risk_text,
    }


def format_feishu_message(data: dict[str, Any]) -> str:
    """Render the locked S14 Feishu template. Raises on invalid input."""

    normalized = _validate_data(data)
    return FEISHU_TEMPLATE.format(
        hotel_name=normalized["hotel_name"],
        period_start=normalized["period_start"],
        period_end=normalized["period_end"],
        final_score_int=f"{normalized['final_score']:.0f}",
        risk_text=normalized["risk_text"],
        report_url=normalized["report_url"],
    )


def format_agent_json_output(agent_output: str) -> str:
    """Parse Agent output as JSON and return the fixed Feishu message.

    If the Agent returns prose, markdown, malformed JSON, or JSON missing
    required fields, do not try to repair it. Return a stable error message.
    """

    if not isinstance(agent_output, str):
        return FORMAT_ERROR_TEXT
    stripped = agent_output.strip()
    if not stripped:
        return FORMAT_ERROR_TEXT
    # 显式拒绝 Markdown / 代码块 / 自然语言
    if stripped.startswith("```") or stripped.startswith("#"):
        return FORMAT_ERROR_TEXT
    try:
        data = json.loads(stripped)
    except (ValueError, TypeError):
        return FORMAT_ERROR_TEXT
    try:
        return format_feishu_message(data)
    except (ValueError, TypeError):
        return FORMAT_ERROR_TEXT


def assert_strict_feishu_format(text: str) -> None:
    """Validate that ``text`` exactly matches the S14 fixed template."""

    expected = format_feishu_message(_expected_payload_from_text(text))
    if text != expected:
        raise ValueError(
            "S14 Feishu text does not match the locked template. "
            "Refusing to send non-conforming text to Feishu."
        )


def _expected_payload_from_text(text: str) -> dict[str, Any]:
    """Best-effort parser used by assert_strict_feishu_format on trusted text."""

    lines = text.splitlines()
    payload: dict[str, Any] = {}

    for line in lines:
        if line.startswith("酒店："):
            payload["hotel_name"] = line[len("酒店："):]
        elif line.startswith("周期："):
            match = re.match(
                r"^周期：(\d{4}-\d{2}-\d{2}) 至 (\d{4}-\d{2}-\d{2})$", line
            )
            if match:
                payload["period_start"] = match.group(1)
                payload["period_end"] = match.group(2)
        elif line.startswith("综合得分："):
            match = re.match(r"^综合得分：(\d+) / 100$", line)
            if match:
                payload["final_score"] = int(match.group(1))
        elif line.startswith("报告链接："):
            payload["report_url"] = line[len("报告链接："):].strip()

    for field in REQUIRED_FIELDS:
        if field not in payload:
            raise ValueError(f"assert_strict_feishu_format: cannot find {field}")
    return {
        "hotel_name": payload["hotel_name"],
        "period_start": payload["period_start"],
        "period_end": payload["period_end"],
        "final_score": int(payload["final_score"]),
        "report_url": payload["report_url"],
    }
