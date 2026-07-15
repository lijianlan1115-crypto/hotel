"""Feishu adapter for the S14 source-selection and report flow.

The current S14 report no longer asks for an OTA channel. Every run uses the
unified ``platform=multi`` diagnosis. A Feishu group user first triggers
``S14诊断`` and chooses either database or Excel:

- database: run the current 23-item server diagnosis immediately;
- Excel: remember ``chat_id + sender_id`` and accept the user's next attachment
  without requiring another @ mention.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

try:
    from .reply_formatter import (
        FORMAT_ERROR_TEXT,
        build_feishu_interactive_card,
        format_feishu_message,
    )
    from .router import should_route_to_s14
    from .source_flow import clear_state, get_state, is_waiting_excel, set_state
except ImportError:
    from reply_formatter import (  # type: ignore
        FORMAT_ERROR_TEXT,
        build_feishu_interactive_card,
        format_feishu_message,
    )
    from router import should_route_to_s14  # type: ignore
    from source_flow import clear_state, get_state, is_waiting_excel, set_state  # type: ignore


PROJECT_ROOT = Path(
    os.environ.get(
        "S14_DIAGNOSIS_PROJECT_ROOT",
        "/opt/openclaw/workspaces/ota-marketing-diagnosis",
    )
)
REPORT_OUTPUT_DIR = Path(
    os.environ.get(
        "S14_REPORT_OUTPUT_DIR",
        "/var/lib/ota-marketing-diagnosis/reports",
    )
)
PUBLIC_BASE_URL = os.environ.get(
    "S14_PUBLIC_BASE_URL",
    "http://47.108.200.194:8081/s14-reports",
).rstrip("/")
HOTEL_ID = os.environ.get("S14_HOTEL_ID", "puyue")
HOTEL_NAME = os.environ.get(
    "S14_HOTEL_NAME",
    "璞悦·奢电竞酒店(贵阳花溪公园店)",
)

_DATABASE_CHOICES = {"数据库", "使用数据库", "从数据库拉取", "database", "db"}
_EXCEL_CHOICES = {"上传excel", "excel", "上传表格", "表格", "上传excel表格"}


def _plain_card(title: str, content: str, *, template: str = "blue") -> dict[str, Any]:
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": template,
                "title": {"tag": "plain_text", "content": title},
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": content},
                }
            ],
        },
    }


def build_source_selection_card() -> dict[str, Any]:
    """Ask only for data source; channel selection has been removed."""

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {
                    "tag": "plain_text",
                    "content": "S14诊断｜请选择数据来源",
                },
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            "本次报告为**整体诊断**，不再区分美团、携程、飞猪等渠道。\n\n"
                            "请选择从服务器数据库读取，或随后上传中文模板 Excel。"
                        ),
                    },
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "type": "primary",
                            "text": {"tag": "plain_text", "content": "数据库"},
                            "value": {
                                "action": "s14_source",
                                "source": "database",
                            },
                        },
                        {
                            "tag": "button",
                            "type": "default",
                            "text": {"tag": "plain_text", "content": "上传Excel"},
                            "value": {
                                "action": "s14_source",
                                "source": "excel",
                            },
                        },
                    ],
                },
            ],
        },
    }


def build_waiting_excel_card() -> dict[str, Any]:
    return _plain_card(
        "S14诊断｜等待Excel附件",
        (
            "**数据来源：Excel**\n\n"
            "请在当前群聊中直接发送 `.xlsx` 或 `.xlsm` 文件，**无需再次@机器人**。\n\n"
            "系统会按当前群聊和当前用户关联本次诊断，等待状态10分钟内有效。"
        ),
        template="turquoise",
    )


def _python_executable() -> str:
    configured = os.environ.get("S14_DIAGNOSIS_PYTHON")
    if configured:
        return configured
    project_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    return str(project_python) if project_python.exists() else sys.executable


def _extract_json(stdout: str) -> dict[str, Any]:
    text = str(stdout or "").strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except ValueError:
        pass

    # Keep the bridge tolerant of harmless launcher logs before the JSON object.
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value = json.loads(text[index:])
            if isinstance(value, dict):
                return value
        except ValueError:
            continue
    raise ValueError("current S14 runner did not return a JSON object")


def _run_current_report(source: str, excel_path: str | None = None) -> dict[str, Any]:
    if not PROJECT_ROOT.exists():
        raise FileNotFoundError(f"S14 project not found: {PROJECT_ROOT}")

    today = date.today()
    period_start = str(today - timedelta(days=29))
    period_end = str(today)
    command = [
        _python_executable(),
        "-m",
        "marketing_diagnosis.main",
        "diagnose-excel" if source == "excel" else "diagnose-db",
    ]
    if source == "excel":
        path = Path(str(excel_path or "")).expanduser().resolve()
        if path.suffix.lower() not in {".xlsx", ".xlsm"}:
            raise ValueError("请上传 .xlsx 或 .xlsm 格式的S14模板")
        if not path.exists():
            raise FileNotFoundError(f"Excel file not found: {path}")
        command.extend(["--excel", str(path)])
    else:
        command.extend(["--dsn-env", "S14_DB_DSN"])

    command.extend(
        [
            "--hotel-id",
            HOTEL_ID,
            "--hotel-name",
            HOTEL_NAME,
            "--platform",
            "multi",
            "--output",
            str(REPORT_OUTPUT_DIR),
        ]
    )
    if source == "database":
        command.extend(["--period-start", period_start, "--period-end", period_end])

    environment = os.environ.copy()
    environment.setdefault("S14_REPORT_OUTPUT_DIR", str(REPORT_OUTPUT_DIR))
    completed = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        env=environment,
        text=True,
        capture_output=True,
        timeout=int(os.environ.get("S14_DIAGNOSIS_TIMEOUT_SECONDS", "300")),
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        raise RuntimeError(f"S14 diagnosis failed: {message}")
    return _extract_json(completed.stdout)


def _report_url(result: dict[str, Any]) -> str:
    existing = str(result.get("report_url") or "").strip()
    if existing.startswith(("http://", "https://")):
        return existing

    report_path = result.get("report_html") or result.get("report_file_path")
    if not report_path:
        raise ValueError("S14 result missing report_html")
    report_file = Path(str(report_path)).resolve()
    root = REPORT_OUTPUT_DIR.resolve()
    try:
        relative = report_file.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"report is outside configured output root: {report_file}") from exc
    return f"{PUBLIC_BASE_URL}/{relative.as_posix()}"


def _reply_payload(result: dict[str, Any], source: str) -> dict[str, Any]:
    visual = result.get("visual_diagnosis") or {}
    score = visual.get("normalized_score")
    if score is None:
        score = result.get("final_score")
    if score is None:
        raise ValueError("S14 result missing normalized score")
    return {
        "hotel_name": result.get("hotel_name") or HOTEL_NAME,
        "period_start": result.get("period_start"),
        "period_end": result.get("period_end"),
        "final_score": float(score),
        "report_url": _report_url(result),
        "data_source": "Excel" if source == "excel" else "数据库",
    }


def _result_card(result: dict[str, Any], source: str) -> dict[str, Any]:
    payload = _reply_payload(result, source)
    card = build_feishu_interactive_card(payload)
    body = card["card"]["elements"][0]["text"]
    body["content"] = f"**数据来源：** {payload['data_source']}\n" + body["content"]
    return card


def _result_text(result: dict[str, Any], source: str) -> str:
    payload = _reply_payload(result, source)
    return f"数据来源：{payload['data_source']}\n" + format_feishu_message(payload)


def handle_source_choice_card(
    source: str,
    *,
    chat_id: str | None = None,
    sender_id: str | None = None,
) -> dict[str, Any]:
    normalized = str(source or "").strip().lower()
    if normalized in {"database", "db", "数据库"}:
        set_state("running_database", chat_id=chat_id, sender_id=sender_id)
        try:
            result = _run_current_report("database")
            clear_state(chat_id=chat_id, sender_id=sender_id)
            return _result_card(result, "database")
        except Exception as exc:
            set_state("awaiting_source", chat_id=chat_id, sender_id=sender_id)
            return _plain_card(
                "S14数据库诊断失败",
                f"**数据来源：数据库**\n\n执行失败：`{exc}`",
                template="red",
            )

    if normalized in {"excel", "上传excel", "上传表格"}:
        set_state("awaiting_excel", chat_id=chat_id, sender_id=sender_id)
        return build_waiting_excel_card()

    return build_source_selection_card()


def handle_source_choice(
    source: str,
    *,
    chat_id: str | None = None,
    sender_id: str | None = None,
) -> str:
    normalized = str(source or "").strip().lower()
    if normalized in {"database", "db", "数据库"}:
        set_state("running_database", chat_id=chat_id, sender_id=sender_id)
        try:
            result = _run_current_report("database")
            clear_state(chat_id=chat_id, sender_id=sender_id)
            return _result_text(result, "database")
        except Exception as exc:
            set_state("awaiting_source", chat_id=chat_id, sender_id=sender_id)
            return f"数据来源：数据库\n诊断执行失败：{exc}"
    if normalized in {"excel", "上传excel", "上传表格"}:
        set_state("awaiting_excel", chat_id=chat_id, sender_id=sender_id)
        return "数据来源：Excel\n请直接发送Excel附件，无需再次@机器人。等待状态10分钟内有效。"
    return "请选择本次数据来源：数据库 / 上传Excel。"


def handle_feishu_text_message_card(
    text: str,
    *,
    chat_id: str | None = None,
    sender_id: str | None = None,
) -> dict[str, Any] | None:
    current = str(text or "").strip()
    normalized = current.lower().replace(" ", "")
    if should_route_to_s14(current):
        set_state("awaiting_source", chat_id=chat_id, sender_id=sender_id)
        return build_source_selection_card()

    state = get_state(chat_id=chat_id, sender_id=sender_id) or {}
    if normalized in _DATABASE_CHOICES and state.get("state") == "awaiting_source":
        return handle_source_choice_card("database", chat_id=chat_id, sender_id=sender_id)
    if normalized in _EXCEL_CHOICES and state.get("state") == "awaiting_source":
        return handle_source_choice_card("excel", chat_id=chat_id, sender_id=sender_id)
    return None


def handle_feishu_text_message(
    text: str,
    *,
    chat_id: str | None = None,
    sender_id: str | None = None,
) -> str | None:
    current = str(text or "").strip()
    normalized = current.lower().replace(" ", "")
    if should_route_to_s14(current):
        set_state("awaiting_source", chat_id=chat_id, sender_id=sender_id)
        return "请选择本次数据来源：数据库 / 上传Excel。当前报告不再区分渠道。"

    state = get_state(chat_id=chat_id, sender_id=sender_id) or {}
    if normalized in _DATABASE_CHOICES and state.get("state") == "awaiting_source":
        return handle_source_choice("database", chat_id=chat_id, sender_id=sender_id)
    if normalized in _EXCEL_CHOICES and state.get("state") == "awaiting_source":
        return handle_source_choice("excel", chat_id=chat_id, sender_id=sender_id)
    return None


def handle_feishu_excel_card(
    file_path: str,
    *,
    chat_id: str | None = None,
    sender_id: str | None = None,
) -> dict[str, Any]:
    # With Feishu identity metadata, an attachment must belong to a pending Excel
    # choice. Without metadata, keep the old command-line direct-upload behavior.
    identity_supplied = bool(chat_id or sender_id)
    if identity_supplied and not is_waiting_excel(chat_id=chat_id, sender_id=sender_id):
        return _plain_card(
            "S14诊断｜尚未选择Excel",
            "请先 `@机器人 S14诊断`，然后选择 **上传Excel**，再发送附件。",
            template="orange",
        )
    try:
        result = _run_current_report("excel", file_path)
        clear_state(chat_id=chat_id, sender_id=sender_id)
        return _result_card(result, "excel")
    except Exception as exc:
        if identity_supplied:
            set_state("awaiting_excel", chat_id=chat_id, sender_id=sender_id)
        return _plain_card(
            "S14 Excel诊断失败",
            f"**数据来源：Excel**\n\n执行失败：`{exc}`\n\n请修正文件后重新发送。",
            template="red",
        )


def handle_feishu_excel(
    file_path: str,
    *,
    chat_id: str | None = None,
    sender_id: str | None = None,
) -> str:
    identity_supplied = bool(chat_id or sender_id)
    if identity_supplied and not is_waiting_excel(chat_id=chat_id, sender_id=sender_id):
        return "请先@机器人发送“S14诊断”，选择上传Excel后再发送附件。"
    try:
        result = _run_current_report("excel", file_path)
        clear_state(chat_id=chat_id, sender_id=sender_id)
        return _result_text(result, "excel")
    except Exception as exc:
        if identity_supplied:
            set_state("awaiting_excel", chat_id=chat_id, sender_id=sender_id)
        return f"数据来源：Excel\n诊断执行失败：{exc}"


def build_feishu_reply(result: dict[str, Any]) -> str:
    """Compatibility wrapper for callers that already own a runtime result."""

    return _result_text(result, str(result.get("data_source") or "database"))


def build_feishu_card_reply(result: dict[str, Any]) -> dict[str, Any]:
    return _result_card(result, str(result.get("data_source") or "database"))


def build_feishu_reply_from_agent_output(agent_output: str) -> str:
    return build_feishu_reply(json.loads(agent_output))


def build_feishu_card_from_agent_output(agent_output: str) -> dict[str, Any]:
    return build_feishu_card_reply(json.loads(agent_output))


__all__ = [
    "FORMAT_ERROR_TEXT",
    "build_feishu_card_from_agent_output",
    "build_feishu_card_reply",
    "build_feishu_reply",
    "build_feishu_reply_from_agent_output",
    "build_source_selection_card",
    "build_waiting_excel_card",
    "handle_feishu_excel",
    "handle_feishu_excel_card",
    "handle_feishu_text_message",
    "handle_feishu_text_message_card",
    "handle_source_choice",
    "handle_source_choice_card",
]
