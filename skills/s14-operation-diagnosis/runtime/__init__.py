"""OpenClaw entrypoint for the current S14 23-item diagnosis.

This runtime intentionally delegates both database and Excel modes to the
``ota-marketing-diagnosis`` project. The retired M01-M08 calculator is no longer
used for Feishu or OpenClaw production reports.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .reply_formatter import build_feishu_interactive_card, format_feishu_message


SKILL_ID = "s14-operation-diagnosis"
PROJECT_ROOT = Path(
    os.environ.get(
        "S14_DIAGNOSIS_PROJECT_ROOT",
        "/opt/openclaw/workspaces/ota-marketing-diagnosis",
    )
)
DEFAULT_OUTPUT_DIR = Path(
    os.environ.get(
        "S14_REPORT_OUTPUT_DIR",
        "/var/lib/ota-marketing-diagnosis/reports",
    )
)
DEFAULT_PUBLIC_BASE_URL = os.environ.get(
    "S14_PUBLIC_BASE_URL",
    "http://47.108.200.194:8081/s14-reports",
).rstrip("/")


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
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value = json.loads(text[index:])
            if isinstance(value, dict):
                return value
        except ValueError:
            continue
    raise ValueError("S14 current engine did not return JSON")


def _risk_level(score: float) -> str:
    return "high" if score < 60 else "medium" if score < 80 else "low"


def _report_url(
    result: dict[str, Any],
    output_dir: Path,
    public_base_url: str,
) -> str:
    existing = str(result.get("report_url") or "").strip()
    if existing.startswith(("http://", "https://")):
        return existing
    report_path = result.get("report_html") or result.get("report_file_path")
    if not report_path:
        raise ValueError("S14 result missing report_html")
    report_file = Path(str(report_path)).resolve()
    try:
        relative = report_file.relative_to(output_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"report outside output root: {report_file}") from exc
    return f"{public_base_url.rstrip('/')}/{relative.as_posix()}"


def _missing_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    visual = result.get("visual_diagnosis") or {}
    return [
        {
            "item_id": item.get("standard_item_id"),
            "item_name": item.get("item_name"),
            "status": item.get("data_status"),
        }
        for item in visual.get("items") or []
        if item.get("data_status") in {"missing", "error", "manual_pending"}
    ]


class S14OperationDiagnosis:
    """Compatibility class used by OpenClaw while running the current engine."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        prepared = dict(inputs or {})
        source_mode = str(prepared.get("data_source_mode") or "database").strip().lower()
        excel_mode = source_mode in {"excel", "excel_upload", "upload_excel"}
        if source_mode not in {"database", "mysql", "excel", "excel_upload", "upload_excel"}:
            raise ValueError(f"S14只支持数据库或Excel，收到: {source_mode}")

        hotel_id = str(prepared.get("hotel_id") or self.config.get("hotel_id") or "puyue")
        hotel_name = str(
            prepared.get("hotel_name")
            or self.config.get("hotel_name")
            or "璞悦·奢电竞酒店(贵阳花溪公园店)"
        )
        today = date.today()
        period_start = str(prepared.get("period_start") or today - timedelta(days=29))
        period_end = str(prepared.get("period_end") or today)
        output_dir = Path(
            prepared.get("output_dir")
            or self.config.get("report_output_dir")
            or DEFAULT_OUTPUT_DIR
        )
        public_base_url = str(
            prepared.get("public_base_url")
            or self.config.get("public_base_url")
            or DEFAULT_PUBLIC_BASE_URL
        ).rstrip("/")

        if not PROJECT_ROOT.exists():
            raise FileNotFoundError(f"S14 project not found: {PROJECT_ROOT}")

        command = [
            _python_executable(),
            "-m",
            "marketing_diagnosis.main",
            "diagnose-excel" if excel_mode else "diagnose-db",
        ]
        if excel_mode:
            excel_path = Path(str(prepared.get("input_excel_path") or "")).expanduser().resolve()
            if excel_path.suffix.lower() not in {".xlsx", ".xlsm"}:
                raise ValueError("S14 Excel模式必须上传.xlsx或.xlsm模板")
            if not excel_path.exists():
                raise FileNotFoundError(f"Excel file not found: {excel_path}")
            command.extend(["--excel", str(excel_path)])
        else:
            command.extend(["--dsn-env", "S14_DB_DSN"])

        command.extend(
            [
                "--hotel-id",
                hotel_id,
                "--hotel-name",
                hotel_name,
                "--platform",
                "multi",
                "--output",
                str(output_dir),
            ]
        )
        if not excel_mode:
            command.extend(
                [
                    "--period-start",
                    period_start,
                    "--period-end",
                    period_end,
                ]
            )

        environment = os.environ.copy()
        environment.setdefault("S14_REPORT_OUTPUT_DIR", str(output_dir))
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
            error = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
            raise RuntimeError(f"S14 diagnosis failed: {error}")

        current = _extract_json(completed.stdout)
        visual = current.get("visual_diagnosis") or {}
        score = visual.get("normalized_score")
        if score is None:
            raise ValueError("S14 current report missing normalized_score")
        score = float(score)
        source_label = "Excel" if excel_mode else "数据库"
        source_value = "excel_upload" if excel_mode else "database"
        url = _report_url(current, output_dir, public_base_url)

        card_payload = {
            "hotel_name": current.get("hotel_name") or hotel_name,
            "period_start": current.get("period_start") or period_start,
            "period_end": current.get("period_end") or period_end,
            "final_score": score,
            "report_url": url,
        }
        card = build_feishu_interactive_card(card_payload)
        card_body = card["card"]["elements"][0]["text"]
        card_body["content"] = f"**数据来源：** {source_label}\n" + card_body["content"]
        message = f"数据来源：{source_label}\n" + format_feishu_message(card_payload)

        return {
            **current,
            "status": current.get("status") or "ok",
            "skill_id": SKILL_ID,
            "hotel_id": current.get("hotel_id") or hotel_id,
            "hotel_name": current.get("hotel_name") or hotel_name,
            "platform": "multi",
            "channel_source": "整体诊断",
            "period_start": current.get("period_start") or period_start,
            "period_end": current.get("period_end") or period_end,
            "raw_score": visual.get("raw_score"),
            "final_score": score,
            "risk_level": _risk_level(score),
            "module_scores": [],
            "caps": [],
            "missing_fields": _missing_items(current),
            "formula_source": "ota-marketing-diagnosis/visual_diagnosis_v14.py",
            "data_source": source_value,
            "execution_steps": [
                {"step": "S01_SELECT_SOURCE", "status": "ok", "detail": source_label},
                {"step": "S02_RUN_CURRENT_23_ITEMS", "status": "ok", "detail": "platform=multi"},
                {"step": "S03_RENDER_HTML", "status": "ok", "detail": url},
            ],
            "calculated_fields": [],
            "mapped_fields": [],
            "field_contract_file": "S14酒店诊断_中文表头上传模板.xlsx",
            "field_mapping_source": "ota-marketing-diagnosis/excel_loader_v2.py",
            "approval_required": False,
            "dry_run": bool(prepared.get("dry_run", True)),
            "report_file_path": current.get("report_html") or current.get("report_file_path"),
            "report_url": url,
            "feishu_message": message,
            "feishu_card": card,
        }


__all__ = ["S14OperationDiagnosis", "SKILL_ID"]
