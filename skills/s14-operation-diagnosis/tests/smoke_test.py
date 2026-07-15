#!/usr/bin/env python3
"""Smoke test for database mode through the current S14 23-item bridge."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="s14_openclaw_") as tmp:
        tmp_dir = Path(tmp)
        output_dir = tmp_dir / "reports"
        report_dir = output_dir / "puyue" / "multi" / "2026-06-16_2026-07-15" / "run-1"
        report_dir.mkdir(parents=True)
        report_file = report_dir / "report.html"
        report_file.write_text("<html><body>23项报告</body></html>", encoding="utf-8")

        engine_result = {
            "status": "ok",
            "hotel_id": "puyue",
            "hotel_name": "璞悦·奢电竞酒店(贵阳花溪公园店)",
            "platform": "multi",
            "period_start": "2026-06-16",
            "period_end": "2026-07-15",
            "report_html": str(report_file),
            "visual_diagnosis": {
                "raw_score": 62.5,
                "normalized_score": 78.0,
                "items": [
                    {
                        "standard_item_id": number,
                        "item_name": f"项目{number}",
                        "data_status": "success",
                    }
                    for number in range(1, 24)
                ],
            },
        }

        sys.path.insert(0, str(ROOT))
        import runtime

        fake_completed = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(engine_result, ensure_ascii=False),
            stderr="",
        )
        with patch.object(runtime, "PROJECT_ROOT", tmp_dir), patch.object(
            runtime.subprocess,
            "run",
            return_value=fake_completed,
        ) as runner:
            result = runtime.S14OperationDiagnosis().execute(
                {
                    "hotel_id": "puyue",
                    "hotel_name": "璞悦·奢电竞酒店(贵阳花溪公园店)",
                    "platform": "meituan",
                    "period_start": "2026-06-16",
                    "period_end": "2026-07-15",
                    "data_source_mode": "database",
                    "output_dir": str(output_dir),
                    "public_base_url": "http://example.test/s14-reports",
                    "dry_run": True,
                }
            )

        command = runner.call_args.args[0]
        assert "diagnose-db" in command, command
        assert "--platform" in command and command[command.index("--platform") + 1] == "multi", command
        assert result["status"] == "ok", result
        assert result["skill_id"] == "s14-operation-diagnosis", result
        assert result["platform"] == "multi", result
        assert result["channel_source"] == "整体诊断", result
        assert result["data_source"] == "database", result
        assert result["final_score"] == 78.0, result
        assert result["module_scores"] == [], result
        assert result["formula_source"].endswith("visual_diagnosis_v14.py"), result
        assert "数据来源：数据库" in result["feishu_message"], result
        assert "**数据来源：** 数据库" in result["feishu_card"]["card"]["elements"][0]["text"]["content"], result
        assert result["report_url"].endswith("/puyue/multi/2026-06-16_2026-07-15/run-1/report.html"), result
        assert Path(result["report_file_path"]).exists(), result

        print("S14 current database smoke test passed")
        print(f"final_score={result['final_score']}")
        print(f"report_file_path={result['report_file_path']}")


if __name__ == "__main__":
    main()
