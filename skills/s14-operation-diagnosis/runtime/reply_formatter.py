"""Strict JSON-to-Feishu formatter for S14.

The Agent may produce diagnostic JSON, but it must not produce the final
Feishu diagnostic card. This module is the single source of truth for the S14
Feishu card. Non-S14 chat should not be constrained by this formatter.
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

# 旧文本模板：只保留给命令行调试和不支持卡片的通道。
FEISHU_TEMPLATE = (
    "【S14 酒店 OTA 诊断报告已生成】\n"
    "\n"
    "酒店：{hotel_name}\n"
    "周期：{period_start} 至 {period_end}\n"
    "综合得分：{final_score_int} / 100\n"
    "风险等级：{risk_text}\n"
    "\n"
    "报告链接：\n"
    "{report_url}\n"
    "\n"
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
    """Render the legacy S14 text template. Raises on invalid input."""

    normalized = _validate_data(data)
    return FEISHU_TEMPLATE.format(
        hotel_name=normalized["hotel_name"],
        period_start=normalized["period_start"],
        period_end=normalized["period_end"],
        final_score_int=f"{normalized['final_score']:.0f}",
        risk_text=normalized["risk_text"],
        report_url=normalized["report_url"],
    )


def build_feishu_interactive_card(data: dict[str, Any]) -> dict[str, Any]:
    """Build a Feishu interactive card with a real button link.

    The report URL is placed on the card button ``url`` field, not inside
    ``plain_text``. This makes Feishu show a clickable card button.
    """

    normalized = _validate_data(data)
    score_text = f"{normalized['final_score']:.0f} / 100"
    report_url = normalized["report_url"]
    content = (
        f"**酒店：** {normalized['hotel_name']}\n"
        f"**周期：** {normalized['period_start']} 至 {normalized['period_end']}\n"
        f"**综合得分：** {score_text}\n"
        f"**风险等级：** {normalized['risk_text']}\n\n"
        "点击下方按钮查看完整网页诊断报告。\n\n"
        "说明：当前为 S14 测试机器人返回结果，不影响正式酒店 OTA Agent。"
    )
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {
                    "tag": "plain_text",
                    "content": "S14 酒店 OTA 诊断报告已生成",
                },
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": content,
                    },
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "查看完整诊断报告",
                            },
                            "type": "primary",
                            "url": report_url,
                        }
                    ],
                },
            ],
        },
    }


def format_feishu_card_json(data: dict[str, Any]) -> str:
    """Render the Feishu interactive card payload as compact JSON text."""

    return json.dumps(build_feishu_interactive_card(data), ensure_ascii=False)


def format_agent_json_output(agent_output: str) -> str:
    """Parse Agent output as JSON and return the legacy Feishu text."""

    if not isinstance(agent_output, str):
        return FORMAT_ERROR_TEXT
    stripped = agent_output.strip()
    if not stripped:
        return FORMAT_ERROR_TEXT
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


def format_agent_json_output_as_card(agent_output: str) -> str:
    """Parse Agent JSON and return a Feishu interactive card JSON string."""

    if not isinstance(agent_output, str):
        return FORMAT_ERROR_TEXT
    stripped = agent_output.strip()
    if not stripped or stripped.startswith("```") or stripped.startswith("#"):
        return FORMAT_ERROR_TEXT
    try:
        data = json.loads(stripped)
    except (ValueError, TypeError):
        return FORMAT_ERROR_TEXT
    try:
        return format_feishu_card_json(data)
    except (ValueError, TypeError):
        return FORMAT_ERROR_TEXT


def assert_strict_feishu_format(text: str) -> None:
    """Validate that ``text`` exactly matches the legacy S14 text template."""

    expected = format_feishu_message(_expected_payload_from_text(text))
    if text != expected:
        raise ValueError(
            "S14 Feishu text does not match the locked template. "
            "Refusing to send non-conforming text to Feishu."
        )


def assert_strict_feishu_card(payload: dict[str, Any]) -> None:
    """Validate that ``payload`` is an S14 interactive card with a button URL."""

    if not isinstance(payload, dict):
        raise ValueError("S14 Feishu card must be a dict")
    if payload.get("msg_type") != "interactive":
        raise ValueError("S14 Feishu card msg_type must be interactive")
    card = payload.get("card")
    if not isinstance(card, dict):
        raise ValueError("S14 Feishu card missing card body")
    elements = card.get("elements")
    if not isinstance(elements, list) or len(elements) < 2:
        raise ValueError("S14 Feishu card missing elements")
    first_text = elements[0].get("text") if isinstance(elements[0], dict) else None
    if not isinstance(first_text, dict) or first_text.get("tag") != "lark_md":
        raise ValueError("S14 Feishu card body must be rendered by lark_md")
    action = elements[1]
    if not isinstance(action, dict) or action.get("tag") != "action":
        raise ValueError("S14 Feishu card must contain an action block")
    actions = action.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("S14 Feishu card action block missing button")
    button = actions[0]
    if not isinstance(button, dict) or button.get("tag") != "button":
        raise ValueError("S14 Feishu card action must be a button")
    if not str(button.get("url") or "").startswith(("http://", "https://")):
        raise ValueError("S14 Feishu card button must contain a report URL")


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
    for i, line in enumerate(lines):
        if line == "报告链接：":
            if i + 1 < len(lines):
                payload["report_url"] = lines[i + 1]
            break

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
