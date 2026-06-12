#!/usr/bin/env python3
"""S14 Feishu entry wrapper.

Routing:
- ``--excel /path/to/file.xlsx``: use the uploaded Excel as the data source.
- ``--text "执行S14诊断"``: use database mode when S14 is triggered.
- ``--format card``: print Feishu interactive card JSON with clickable button.
- Non-S14 text gets a normal text reply instead of the S14 error template.
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
    return "收到。普通问题可以正常回复；需要生成 S14 OTA 诊断报告时，请发送“S14诊断”或上传诊断 Excel。"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run S14 Feishu reply entry")
    parser.add_argument("--text", default="", help="Feishu text message")
    parser.add_argument("--excel", default="", help="Downloaded Feishu Excel path")
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
    )

    if args.excel:
        reply = handle_feishu_excel_card(args.excel) if args.format == "card" else handle_feishu_excel(args.excel)
    elif args.text:
        reply = (
            handle_feishu_text_message_card(args.text)
            if args.format == "card"
            else handle_feishu_text_message(args.text)
        )
        if reply is None:
            reply = _normal_reply(args.text)
    else:
        reply = ""

    return _print_reply(reply, FORMAT_ERROR_TEXT)


if __name__ == "__main__":
    raise SystemExit(main())
