"""Feishu adapter for auto-triggering S14."""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from .router import should_route_to_s14
    from .reply_formatter import (
        FORMAT_ERROR_TEXT,
        handle_feishu_excel,
        handle_feishu_text_message,
    )
    from .excel_reader import run_s14_from_excel
except ImportError:
    from router import should_route_to_s14
    from reply_formatter import (
        FORMAT_ERROR_TEXT,
        handle_feishu_excel,
        handle_feishu_text_message,
    )
    from excel_reader import run_s14_from_excel

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
LOCAL_RUNNER = PACKAGE_ROOT / "scripts/s14_local_report.py"
S14_DB_DSN = os.environ.get("S14_DB_DSN") or os.environ.get("HOTEL_OTA_DB_DSN")
S14_REPORT_OUTPUT_DIR = os.environ.get(
    "S14_REPORT_OUTPUT_DIR",
    "/opt/openclaw/workspaces/s14-feishu-test/public/s14-reports",
)
S14_PUBLIC_BASE_URL = os.environ.get(
    "S14_PUBLIC_BASE_URL",
    "http://47.108.200.194:8088/s14-reports",
)
S14_REPORT_RETENTION_DAYS = int(os.environ.get("S14_REPORT_RETENTION_DAYS", "30"))


def build_feishu_reply(result: dict[str, Any]) -> str:
    """Always return fixed text template; disable card output."""
    try:
        return handle_feishu_text_message(result)
    except Exception:
        return FORMAT_ERROR_TEXT