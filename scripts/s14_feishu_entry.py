#!/usr/bin/env python3
"""S14 Feishu entry wrapper.

Group flow:
1. Text ``S14诊断`` -> return database / Excel source-selection card.
2. Button callback -> pass ``--source-choice database|excel`` with chat/sender ids.
3. When Excel was chosen, the next attachment message can call ``--excel`` with
   the same chat/sender ids; no @ mention is required.

All diagnoses use the unified ``platform=multi`` report and do not ask for an OTA
channel.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
S14_ROOT = ROOT / "skills" / "s14-operation-diagnosis"
ENV_FILE = Path("/etc/hotel-ota-ai/hotel-ota.env")


def _load_env_file() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _print_reply(reply: Any, error_text: str) -> int:
    if not reply:
        print(error_text)
        return 2
    if isinstance(reply, (dict, list)):
        print(json.dumps(reply, ensure_ascii=False))
    else:
        print(reply)
    return 0


def _normal_reply(text: str) -> str:
    current = str(text or "").strip()
    now = datetime.now()
    if any(word in current for word in ("今天", "日期", "几号", "几月几日")):
        return f"今天是 {now:%Y-%m-%d}。"
    if any(word in current for word in ("几点", "时间", "现在时间")):
        return f"现在时间是 {now:%Y-%m-%d %H:%M:%S}。"
    return "收到。需要生成 S14 诊断报告时，请发送“S14诊断”。"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run S14 Feishu reply entry")
    parser.add_argument("--text", default="", help="Feishu text message")
    parser.add_argument("--excel", default="", help="Downloaded Feishu Excel path")
    parser.add_argument(
        "--source-choice",
        default="",
        choices=("", "database", "excel", "数据库", "上传Excel"),
        help="Source-selection button callback value.",
    )
    parser.add_argument(
        "--chat-id",
        default=os.environ.get("FEISHU_CHAT_ID", ""),
        help="Feishu chat_id used to associate a later attachment.",
    )
    parser.add_argument(
        "--sender-id",
        default=os.environ.get("FEISHU_SENDER_ID", ""),
        help="Feishu sender open_id/user_id used to associate a later attachment.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "card"),
        default=os.environ.get("S14_FEISHU_REPLY_FORMAT", "card"),
        help="Output format. card prints Feishu interactive card JSON.",
    )
    args = parser.parse_args()

    _load_env_file()
    sys.path.insert(0, str(S14_ROOT))

    from runtime.feishu_adapter import (  # noqa: WPS433
        FORMAT_ERROR_TEXT,
        handle_feishu_excel,
        handle_feishu_excel_card,
        handle_feishu_text_message,
        handle_feishu_text_message_card,
        handle_source_choice,
        handle_source_choice_card,
    )

    identity = {
        "chat_id": args.chat_id or None,
        "sender_id": args.sender_id or None,
    }

    if args.source_choice:
        reply = (
            handle_source_choice_card(args.source_choice, **identity)
            if args.format == "card"
            else handle_source_choice(args.source_choice, **identity)
        )
    elif args.excel:
        reply = (
            handle_feishu_excel_card(args.excel, **identity)
            if args.format == "card"
            else handle_feishu_excel(args.excel, **identity)
        )
    elif args.text:
        reply = (
            handle_feishu_text_message_card(args.text, **identity)
            if args.format == "card"
            else handle_feishu_text_message(args.text, **identity)
        )
        if reply is None:
            reply = _normal_reply(args.text)
    else:
        reply = ""

    return _print_reply(reply, FORMAT_ERROR_TEXT)


if __name__ == "__main__":
    raise SystemExit(main())
