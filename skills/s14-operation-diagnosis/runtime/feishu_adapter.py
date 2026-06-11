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
except ImportError:
    from router import build_control_inputs, should_route_to_s14
    from reply_formatter import (
        FORMAT_ERROR_TEXT,
        assert_strict_feishu_format,
        format_agent_json_output,
        format_feishu_message,
    )


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
LOCAL_RUNNER = PACKAGE_ROOT / "scripts/s14_local_report.py"

# S14 MySQL 配置 (从环境变量读取，提供默认值)
S14_DB_DSN = os.environ.get(
    "S14_DB_DSN",
    "mysql://openclaw_user:OpenClaw_123456@47.108.200.194:3306/hotel_pricing"
)
S14_REPORT_OUTPUT_DIR = os.environ.get(
    "S14_REPORT_OUTPUT_DIR",
    "/opt/openclaw/workspaces/s14-feishu-test/public/s14-reports"
)
S14_PUBLIC_BASE_URL = os.environ.get(
    "S14_PUBLIC_BASE_URL",
    "http://47.108.200.194:8088/s14-reports"
)


def run_s14_local_table_mode() -> dict[str, Any]:
    """Run S14 Skill via MySQL data source and return structured result.

    S14 严格只接受 MySQL 数据库或 Excel 上传两种数据源（其他来源一律拒绝）。
    此方法通过 S14OperationDiagnosis 直接调用 MySQL 数据。
    """

    sys.path.insert(0, str(PACKAGE_ROOT.parent))
    try:
        from datetime import date, timedelta
        from runtime import S14OperationDiagnosis
    except ImportError as exc:
        raise RuntimeError(f"S14 Skill runtime not importable: {exc}") from exc

    today = date.today()
    period_start = today - timedelta(days=9)
    period_end = today

    diagnosis = S14OperationDiagnosis({
        "db_kind": "mysql",
        "db_dsn": S14_DB_DSN,
        "report_output_dir": S14_REPORT_OUTPUT_DIR,
        "public_base_url": S14_PUBLIC_BASE_URL,
    })
    return diagnosis.execute({
        "hotel_id": "puyue",
        "platform": "fliggy",
        "period_start": str(period_start),
        "period_end": str(period_end),
        "data_source_mode": "database",
    })


def build_feishu_reply(result: dict[str, Any]) -> str:
    """Build the locked S14 Feishu reply from a Skill result.

    强制逻辑：始终从 result 字段重新渲染固定模板，不直接信任
    ``result["feishu_message"]``。如果 Skill 内部任何代码改了模板、漏了
    字段、或者拼出非固定格式的字符串，Bot 端会忽略它，按 5 个原始字段
    重新跑 ``format_feishu_message`` 拿到标准 6 段文本。
    """

    try:
        rendered = format_feishu_message(result)
    except Exception:
        return FORMAT_ERROR_TEXT
    # 二次断言：保证发到飞书的文本与模板逐字符一致。
    try:
        assert_strict_feishu_format(rendered)
    except ValueError:
        return FORMAT_ERROR_TEXT
    return rendered


def build_feishu_reply_from_agent_output(agent_output: str) -> str:
    """Use when an Agent first produces JSON, then Python renders Feishu text.

    Bot 唯一允许让 Agent 参与的入口。Agent 输出必须是合法 JSON 对象。
    一切非 JSON、Markdown、代码块、自然语言、缺字段都会被识别为错误，
    统一回 ``FORMAT_ERROR_TEXT``，**不允许** Bot 自行拼接"飞猪诊断：xx/100"等
    自由文本。
    """

    rendered = format_agent_json_output(agent_output)
    # 成功路径下 ``format_agent_json_output`` 已经走 ``format_feishu_message``，
    # 必定等于 FEISHU_TEMPLATE 的渲染结果；失败路径下就是 FORMAT_ERROR_TEXT。
    # 这里再断言一次防止未来回归。
    try:
        assert_strict_feishu_format(rendered)
    except ValueError:
        return FORMAT_ERROR_TEXT
    return rendered


def handle_feishu_text_message(text: str) -> str | None:
    """Return reply text if this message should trigger S14, otherwise None."""

    if not should_route_to_s14(text):
        return None
    _control_inputs = build_control_inputs(text)
    result = run_s14_local_table_mode()
    return build_feishu_reply(result)
