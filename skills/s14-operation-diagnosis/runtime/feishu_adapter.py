"""Feishu adapter for auto-triggering S14.

This file is for the Feishu entry service to import or copy. Feishu users do
not run Python manually: the already-running Feishu bot calls this adapter
after receiving a message event.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

try:
    from .router import build_control_inputs, should_route_to_s14
    from .reply_formatter import (
        FORMAT_ERROR_TEXT,
        assert_strict_feishu_format,
        format_agent_json_output,
        format_feishu_message,
    )
    from .excel_reader import run_s14_from_excel
except ImportError:
    from router import build_control_inputs, should_route_to_s14
    from reply_formatter import (
        FORMAT_ERROR_TEXT,
        assert_strict_feishu_format,
        format_agent_json_output,
        format_feishu_message,
    )
    from excel_reader import run_s14_from_excel


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
LOCAL_RUNNER = PACKAGE_ROOT / "scripts/s14_local_report.py"

S14_DB_DSN = os.environ.get(
    "S14_DB_DSN",
    "mysql://openclaw_user:OpenClaw_123456@47.108.200.194:3306/hotel_pricing",
)

S14_REPORT_OUTPUT_DIR = os.environ.get(
    "S14_REPORT_OUTPUT_DIR",
    "/opt/openclaw/workspaces/s14-feishu-test/public/s14-reports",
)

S14_PUBLIC_BASE_URL = os.environ.get(
    "S14_PUBLIC_BASE_URL",
    "http://47.108.200.194:8088/s14-reports",
)


def run_s14_local_table_mode() -> dict[str, Any]:
    """Run S14 Skill via MySQL data source and return structured result."""

    sys.path.insert(0, str(PACKAGE_ROOT.parent))
    try:
        from datetime import date, timedelta
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
    """Build the locked S14 Feishu reply from a Skill result."""

    try:
        rendered = format_feishu_message(result)
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
    """文字触发时，永远走数据库模式，不读取上一次 Excel 结果。"""

    if not should_route_to_s14(text):
        return None

    result = run_s14_local_table_mode()
    return build_feishu_reply(result)

def handle_feishu_excel(file_path: str) -> str:
    """Handle a downloaded Feishu Excel attachment.

    Feishu Gateway 需要先把 Excel 附件下载到服务器本地路径，
    然后调用这个函数：

        handle_feishu_excel("/tmp/xxx.xlsx")

    本函数只负责：
    1. 调用 S14 Excel 模式；
    2. 生成 HTML 报告；
    3. 返回固定飞书 6 段文本。
    """

    try:
        result = run_s14_from_excel(
            file_path,
            {
                "report_output_dir": S14_REPORT_OUTPUT_DIR,
                "public_base_url": S14_PUBLIC_BASE_URL,
            },
        )

        # 优先使用 S14 已生成好的标准飞书消息
        if isinstance(result, dict) and result.get("feishu_message"):
            return result["feishu_message"]

        return build_feishu_reply(result)

    except Exception:
        return FORMAT_ERROR_TEXT
