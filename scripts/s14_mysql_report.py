#!/usr/bin/env python3
"""Compatibility wrapper for legacy S14 MySQL report command."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ENTRY = Path(__file__).resolve().with_name("s14_feishu_entry.py")


if __name__ == "__main__":
    raise SystemExit(
        subprocess.run(
            [sys.executable, str(ENTRY), "--text", "执行S14诊断"],
            check=False,
            text=True,
        ).returncode
    )

