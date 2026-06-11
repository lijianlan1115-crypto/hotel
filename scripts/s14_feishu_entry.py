#!/usr/bin/env python3
"""S14 Feishu entry wrapper.

This is the only script OpenClaw should call for S14 Feishu replies.

Routing:
- ``--excel /path/to/file.xlsx``: use the uploaded Excel as the data source.
- ``--text "执行S14诊断"``: use database mode.

The script prints the locked Feishu message only. It must not print JSON,
debug text, module tables, or old report links.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run S14 Feishu fixed reply entry")
    parser.add_argument("--text", default="", help="Feishu text message")
    parser.add_argument("--excel", default="", help="Downloaded Feishu Excel path")
    args = parser.parse_args()

    _load_env_file()
    sys.path.insert(0, str(S14_ROOT))

    from runtime.feishu_adapter import (  # noqa: WPS433
        FORMAT_ERROR_TEXT,
        handle_feishu_excel,
        handle_feishu_text_message,
    )

    if args.excel:
        reply = handle_feishu_excel(args.excel)
    elif args.text:
        reply = handle_feishu_text_message(args.text) or ""
    else:
        reply = ""

    if reply:
        print(reply)
    else:
        print(FORMAT_ERROR_TEXT)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

