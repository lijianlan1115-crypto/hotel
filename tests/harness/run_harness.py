#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"

SUITES = {
    "p0-safety": ["p0_safety.json"],
    "s4-calendar": ["s4_calendar.json"],
    "s4-market": ["s4_market_mcp.json"],
    "s5-s6-pricing": ["s5_s6_pricing.json"],
    "s16-progress": ["s16_progress.json"],
    "command-menu": ["command_menu.json"],
}
SUITES["all"] = [name for files in SUITES.values() for name in files]


def _load_scenarios(suite: str) -> list[dict[str, Any]]:
    files = SUITES.get(suite)
    if not files:
        raise ValueError(f"unknown suite: {suite}")
    scenarios: list[dict[str, Any]] = []
    for file_name in files:
        path = SCENARIO_DIR / file_name
        with open(path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        scenarios.extend(loaded if isinstance(loaded, list) else loaded.get("scenarios", []))
    return scenarios


def _replace_tokens(value: str, tokens: dict[str, str]) -> str:
    for key, token_value in tokens.items():
        value = value.replace("${" + key + "}", token_value)
    return value


def _command_args(command: str | list[str], tokens: dict[str, str]) -> list[str]:
    parts = command if isinstance(command, list) else shlex.split(command)
    replaced = [_replace_tokens(str(part), tokens) for part in parts]
    if replaced and replaced[0] in {"python", "python3"}:
        replaced[0] = sys.executable
    return replaced


def _json_path(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current


def _assert_expectations(scenario: dict[str, Any], stdout: str, returncode: int) -> dict[str, Any]:
    expect = scenario.get("expect") or {}
    if returncode != int(expect.get("returncode", 0)):
        return {"ok": False, "reason": f"returncode {returncode}", "stdout": stdout}
    for text in expect.get("forbid_text", []):
        if text in stdout:
            return {"ok": False, "reason": f"forbidden text found: {text}", "stdout": stdout}
    for text in expect.get("contains_text", []):
        if text not in stdout:
            return {"ok": False, "reason": f"required text missing: {text}", "stdout": stdout}
    payload = None
    if expect.get("json_path") or "status" in expect or "blocked_reason" in expect:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            return {"ok": False, "reason": f"invalid json: {exc}", "stdout": stdout}
    if "status" in expect and payload.get("status") != expect["status"]:
        return {"ok": False, "reason": f"status {payload.get('status')}", "stdout": stdout}
    if "blocked_reason" in expect and payload.get("blocked_reason") != expect["blocked_reason"]:
        return {"ok": False, "reason": f"blocked_reason {payload.get('blocked_reason')}", "stdout": stdout}
    for path, expected in (expect.get("json_path") or {}).items():
        actual = _json_path(payload, path)
        if actual != expected:
            return {"ok": False, "reason": f"{path} expected {expected!r}, got {actual!r}", "stdout": stdout}
    return {"ok": True}


def run_suite(suite: str) -> int:
    scenarios = _load_scenarios(suite)
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        tokens = {
            "ROOT": str(ROOT),
            "DB": str(Path(tmp) / "hotel_ops.sqlite"),
        }
        for scenario in scenarios:
            command = _command_args(scenario["command"], tokens)
            env = os.environ.copy()
            env.update({key: _replace_tokens(str(value), tokens) for key, value in (scenario.get("env") or {}).items()})
            completed = subprocess.run(command, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=int(scenario.get("timeout", 30)))
            result = _assert_expectations(scenario, completed.stdout.strip(), completed.returncode)
            result.update({"id": scenario["id"], "command": command})
            results.append(result)
    failed = [result for result in results if not result["ok"]]
    print(json.dumps({"status": "ok" if not failed else "failed", "suite": suite, "total": len(results), "failed": failed, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hotel OTA business scenario harness")
    parser.add_argument("--suite", choices=sorted(SUITES), required=True)
    args = parser.parse_args(argv)
    return run_suite(args.suite)


if __name__ == "__main__":
    raise SystemExit(main())
