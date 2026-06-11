"""Lightweight routing helpers for Feishu/OpenClaw entry services.

This module only decides whether a message should call S14 and builds control
inputs. It must not calculate scores or format business results.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TRIGGERS_FILE = ROOT / "config/triggers.yaml"


def _load_trigger_text() -> str:
    return TRIGGERS_FILE.read_text(encoding="utf-8")


def _yaml_list(text: str, key: str) -> list[str]:
    lines = text.splitlines()
    values: list[str] = []
    active = False
    for line in lines:
        if line.startswith(f"{key}:"):
            active = True
            continue
        if active and line and not line.startswith(" ") and not line.startswith("-"):
            break
        if active:
            item = line.strip()
            if item.startswith("- "):
                values.append(item[2:].strip().strip('"').strip("'"))
    return values


def should_route_to_s14(message: str) -> bool:
    trigger_text = _load_trigger_text()
    phrases = _yaml_list(trigger_text, "trigger_phrases")
    normalized = message.lower()
    return any(phrase.lower() in normalized for phrase in phrases)


def build_control_inputs(message: str, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    defaults = defaults or {}
    today = date.today()
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", message)
    period_start = dates[0] if dates else str(today - timedelta(days=int(defaults.get("default_period_days", 10)) - 1))
    period_end = dates[1] if len(dates) > 1 else str(today)

    platform = defaults.get("platform") or _platform_from_text(message) or "fliggy"
    return {
        "hotel_id": defaults.get("hotel_id", "puyue"),
        "platform": platform,
        "period_start": period_start,
        "period_end": period_end,
        "hotel_name": defaults.get("hotel_name"),
        "channel_source": defaults.get("channel_source") or _channel_source(platform),
        "output_dir": defaults.get("output_dir", "./outputs"),
        "public_base_url": defaults.get("public_base_url"),
        "dry_run": True,
    }


def _platform_from_text(message: str) -> str | None:
    aliases = {
        "fliggy": ["飞猪", "fliggy"],
        "meituan": ["美团", "meituan"],
        "ctrip": ["携程", "ctrip"],
        "qunar": ["去哪儿", "qunar"],
        "douyin": ["抖音", "douyin"],
        "multi": ["多渠道", "全渠道", "multi"],
    }
    normalized = message.lower()
    for platform, names in aliases.items():
        if any(name.lower() in normalized for name in names):
            return platform
    return None


def _channel_source(platform: str) -> str:
    return {
        "fliggy": "飞猪",
        "meituan": "美团",
        "ctrip": "携程",
        "qunar": "去哪儿",
        "douyin": "抖音",
        "multi": "多渠道",
    }.get(platform, platform)
