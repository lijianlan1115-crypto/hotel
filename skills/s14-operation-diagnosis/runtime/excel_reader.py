from pathlib import Path
from typing import Any


def build_excel_inputs(file_path: str) -> dict[str, Any]:
    path = Path(file_path).expanduser().resolve()

    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    return {
        "hotel_id": "puyue",
        "hotel_name": "贵阳璞悦·奢电竞酒店",
        "platform": "fliggy",
        "period_start": "2026-06-01",
        "period_end": "2026-06-10",
        "data_source_mode": "excel_upload",
        "input_excel_path": str(path),
        "dry_run": True,
    }


def run_s14_from_excel(file_path: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        from . import S14OperationDiagnosis
    except ImportError:
        from runtime import S14OperationDiagnosis

    runtime_config = config or {}
    inputs = build_excel_inputs(file_path)
    return S14OperationDiagnosis(runtime_config).execute(inputs)
