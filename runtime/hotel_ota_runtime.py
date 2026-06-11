#!/usr/bin/env python3
"""Compatibility entrypoint for the Hotel OTA OpenClaw runtime."""

from __future__ import annotations

import sys
from pathlib import Path


PACKAGE_PARENT = Path(__file__).resolve().parents[1]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from runtime.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
