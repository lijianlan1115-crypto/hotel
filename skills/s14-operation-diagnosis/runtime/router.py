"""Lightweight routing helpers for Feishu/OpenClaw entry services.

This module only decides whether a message should call S14 and builds control
inputs. The current S14 diagnosis is channel-independent: ``platform`` is always
``multi`` and the Feishu flow asks only for database or Excel as the data source.
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
    normalized = str(message or "").lower()
    return any(phrase.lower() in normalized for phrase in phrases)


def build_control_inputs(message: str, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    defaults = defaults or {}
    today = date.today()
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", str(message or ""))
    default_days = int(defaults.get("default_period_days", 30))
    period_start = dates[0] if dates else str(today - timedelta(days=default_days - 1))
    period_end = dates[1] if len(dates) > 1 else str(today)

    return {
        "hotel_id": defaults.get("hotel_id", "puyue"),
        "platform": "multi",
        "period_start": period_start,
        "period_end": period_end,
        "hotel_name": defaults.get("hotel_name"),
        "channel_source": "整体诊断",
        "output_dir": defaults.get("output_dir", "./outputs"),
        "public_base_url": defaults.get("public_base_url"),
        "dry_run": True,
    }


def _platform_from_text(message: str) -> str:
    """Compatibility helper retained for old callers; always return multi."""

    return "multi"


def _channel_source(platform: str) -> str:
    return "整体诊断"


__all__ = [
    "build_control_inputs",
    "should_route_to_s14",
]
