#!/usr/bin/env python3
"""Compatibility wrapper for S14 Feishu diagnosis.

Do not keep diagnosis logic in this legacy script. OpenClaw may still call this
path from older prompts, so it delegates to ``scripts/s14_feishu_entry.py`` and
prints only the fixed Feishu reply.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ENTRY = Path(__file__).resolve().with_name("s14_feishu_entry.py")


def main() -> int:
    text = "执行S14诊断"
    if len(sys.argv) > 1 and sys.argv[1].lower() in {"fliggy", "feizhu", "飞猪"}:
        text = "飞猪诊断"
    completed = subprocess.run(
        [sys.executable, str(ENTRY), "--text", text],
        check=False,
        text=True,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

