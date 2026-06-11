"""Feishu adapter for auto-triggering S14.

This file is for the Feishu entry service to import or copy. Feishu users do
not run Python manually: the already-running Feishu bot calls this adapter
after receiving a message event.
"""

from __future__ import annotations

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
        assert_strict_feishu_format,
        format_agent_json_output,
        format_feishu_message,
    )
    from .excel_reader import run_s14_from_excel
except ImportError:
    from router import should_route_to_s14
    from reply_formatter import (
        FORMAT_ERROR_TEXT,
        assert_strict_feishu_format,
        format_agent_json_output,
        format_feishu_message,
    )
    from excel_reader import run_s14_from_excel


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
LOCAL_RUNNER = PACKAGE_ROOT / "scripts/s14_local_report.py"

# Production credentials must be injected by the service environment.
# Do not hardcode real DB credentials in the Skill repository.
S14_DB_DSN = os.environ.get("S14_DB_DSN") or os.environ.get("HOTEL_OTA_DB_DSN")

S14_REPORT_OUTPUT_DIR = os.environ.get(
    "S14_REPORT_OUTPUT_DIR",
    "/opt/openclaw/workspaces/s14-feishu-test/public/s14-reports",
)

S14_PUBLIC_BASE_URL = os.environ.get(
    "S14_PUBLIC_BASE_URL",
    "http://47.108.200.194:8088/s14-reports",
)


def _new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _append_run_id(report_url: str, run_id: str) -> str:
    """Append/replace run_id so Feishu/browser cannot show a stale cached page."""

    if not report_url:
        return report_url
    parts = urlsplit(str(report_url))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["run_id"] = run_id
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _prepare_current_result(result: dict[str, Any]) -> dict[str, Any]:
    """Force the reply to be rebuilt from the current run result only.

    Some entry services or Agent layers may pass through an older prebuilt
    ``feishu_message``. S14 must not trust that field here: it is removed and
    rendered again by ``runtime/reply_formatter.py`` from the current result.
    """

    prepared = dict(result or {})
    run_id = str(prepared.get("run_id") or _new_run_id())
    prepared["run_id"] = run_id
    if prepared.get("report_url"):
        prepared["report_url"] = _append_run_id(prepared["report_url"], run_id)
    prepared.pop("feishu_message", None)
    return prepared


def run_s14_local_table_mode() -> dict[str, Any]:
    """Run S14 Skill via MySQL data source and return structured result."""

    if not S14_DB_DSN:
        raise RuntimeError("S14 database mode requires S14_DB_DSN or HOTEL_OTA_DB_DSN")

    sys.path.insert(0, str(PACKAGE_ROOT.parent))
    try:
        from runtime import S14OperationDiagnosis
    except ImportError as exc:
        raise RuntimeError(f"S14 Skill runtime not importable: {exc}") from exc

    today = date.today()
    period_start = today - timedelta(days=9)
    period_end = today

    diagnosis = S14OperationDiagnosis(
        {
            "db_kind": "mysql",
            "db_dsn": S14_DB_DSN,
            "report_output_dir": S14_REPORT_OUTPUT_DIR,
            "public_base_url": S14_PUBLIC_BASE_URL,
        }
    )

    return diagnosis.execute(
        {
            "hotel_id": "puyue",
            "platform": "fliggy",
            "period_start": str(period_start),
            "period_end": str(period_end),
            "data_source_mode": "database",
        }
    )


def build_feishu_reply(result: dict[str, Any]) -> str:
    """Build the locked S14 Feishu reply from the current Skill result."""

    try:
        rendered = format_feishu_message(_prepare_current_result(result))
    except Exception:
        return FORMAT_ERROR_TEXT

    try:
        assert_strict_feishu_format(rendered)
    except ValueError:
        return FORMAT_ERROR_TEXT

    return rendered


def build_feishu_reply_from_agent_output(agent_output: str) -> str:
    """Use when an Agent first produces JSON, then Python renders Feishu text."""

    rendered = format_agent_json_output(agent_output)

    try:
        assert_strict_feishu_format(rendered)
    except ValueError:
        return FORMAT_ERROR_TEXT

    return rendered


def handle_feishu_text_message(text: str) -> str | None:
    """Text trigger always runs a fresh database diagnosis.

    Never answer from previous Feishu messages, Agent memory, old JSON, or a
    prebuilt ``feishu_message``. The only outbound message is the current run's
    locked template rendered by ``build_feishu_reply``.
    """

    if not should_route_to_s14(text):
        return None

    try:
        result = run_s14_local_table_mode()
        return build_feishu_reply(result)
    except Exception:
        return FORMAT_ERROR_TEXT

def handle_feishu_excel(file_path: str) -> str:
    """Excel upload always runs the uploaded workbook and returns fixed text."""

    try:
        result = run_s14_from_excel(
            file_path,
            {
                "report_output_dir": S14_REPORT_OUTPUT_DIR,
                "public_base_url": S14_PUBLIC_BASE_URL,
            },
        )
        return build_feishu_reply(result)

    except Exception:
        return FORMAT_ERROR_TEXT
