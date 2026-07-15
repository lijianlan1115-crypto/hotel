#!/usr/bin/env python3
"""Smoke test for Excel mode through the current S14 23-item bridge."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]


def create_minimal_xlsx(path: Path) -> None:
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
</Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheets/>
</workbook>""",
        )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="s14_excel_") as tmp:
        tmp_dir = Path(tmp)
        excel_path = tmp_dir / "S14酒店诊断_中文表头上传模板.xlsx"
        create_minimal_xlsx(excel_path)

        output_dir = tmp_dir / "reports"
        report_dir = output_dir / "puyue" / "multi" / "2026-06-16_2026-07-15" / "run-excel"
        report_dir.mkdir(parents=True)
        report_file = report_dir / "report.html"
        report_file.write_text("<html><body>Excel 23项报告</body></html>", encoding="utf-8")

        engine_result = {
            "status": "ok",
            "hotel_id": "puyue",
            "hotel_name": "璞悦·奢电竞酒店(贵阳花溪公园店)",
            "platform": "multi",
            "period_start": "2026-06-16",
            "period_end": "2026-07-15",
            "report_html": str(report_file),
            "visual_diagnosis": {
                "raw_score": 64.0,
                "normalized_score": 80.0,
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
                    "platform": "fliggy",
                    "data_source_mode": "excel_upload",
                    "input_excel_path": str(excel_path),
                    "output_dir": str(output_dir),
                    "public_base_url": "http://example.test/s14-reports",
                    "dry_run": True,
                }
            )

        command = runner.call_args.args[0]
        assert "diagnose-excel" in command, command
        assert "--excel" in command and command[command.index("--excel") + 1] == str(excel_path), command
        assert "--platform" in command and command[command.index("--platform") + 1] == "multi", command
        assert result["status"] == "ok", result
        assert result["data_source"] == "excel_upload", result
        assert result["platform"] == "multi", result
        assert result["channel_source"] == "整体诊断", result
        assert result["final_score"] == 80.0, result
        assert result["module_scores"] == [], result
        assert "数据来源：Excel" in result["feishu_message"], result
        assert "**数据来源：** Excel" in result["feishu_card"]["card"]["elements"][0]["text"]["content"], result
        assert result["field_mapping_source"] == "ota-marketing-diagnosis/excel_loader_v2.py", result
        assert Path(result["report_file_path"]).exists(), result

        print("S14 current Excel smoke test passed")
        print(f"final_score={result['final_score']}")
        print(f"report_file_path={result['report_file_path']}")


if __name__ == "__main__":
    main()
