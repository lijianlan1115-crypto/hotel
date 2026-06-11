#!/usr/bin/env python3
"""Smoke test for Excel upload mode with Chinese headers."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


ROOT = Path(__file__).resolve().parents[1]


def xml_escape(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def make_cell(col: int, row: int, value: object) -> str:
    col_name = ""
    n = col
    while n:
        n, rem = divmod(n - 1, 26)
        col_name = chr(65 + rem) + col_name
    ref = f"{col_name}{row}"
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{xml_escape(value)}</t></is></c>'


def create_xlsx(path: Path) -> None:
    rows = [
        ["日期", "酒店ID", "渠道", "平均房价", "出租率", "RevPAR", "可售间夜", "曝光量", "浏览量", "浏览-支付转化", "推广订单金额", "推广花费", "平台评分"],
        ["2026-06-01", "puyue", "飞猪", 140, "82%", 160, 300, 9000, 1000, "3%", 12000, 2000, 4.7],
    ]
    sheet_rows = []
    for r_idx, row in enumerate(rows, 1):
        cells = "".join(make_cell(c_idx, r_idx, value) for c_idx, value in enumerate(row, 1))
        sheet_rows.append(f'<row r="{r_idx}">{cells}</row>')
    sheet_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>{''.join(sheet_rows)}</sheetData>
</worksheet>'''
    with ZipFile(path, "w", ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>''')
        zf.writestr("_rels/.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>''')
        zf.writestr("xl/workbook.xml", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="S14上传数据" sheetId="1" r:id="rId1"/></sheets>
</workbook>''')
        zf.writestr("xl/_rels/workbook.xml.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>''')
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="s14_excel_") as tmp:
        tmp_dir = Path(tmp)
        excel_path = tmp_dir / "uploaded.xlsx"
        output_dir = tmp_dir / "outputs"
        create_xlsx(excel_path)

        sys.path.insert(0, str(ROOT))
        from runtime import S14OperationDiagnosis

        result = S14OperationDiagnosis({"db_kind": "sqlite", "db_dsn": ":memory:"}).execute(
            {
                "hotel_id": "puyue",
                "platform": "fliggy",
                "period_start": "2026-06-01",
                "period_end": "2026-06-10",
                "data_source_mode": "excel_upload",
                "input_excel_path": str(excel_path),
                "output_dir": str(output_dir),
                "dry_run": True,
            }
        )

        assert result["status"] in {"ok", "partial"}, result
        assert result["data_source"] == "excel_upload", result
        assert result["channel_source"] in {None, "飞猪"}, result
        assert len(result["module_scores"]) == 8, result
        assert result["final_score"] > 0, result
        assert Path(result["report_file_path"]).exists(), result
        assert "【S14 酒店 OTA 诊断报告已生成】" in result["feishu_message"], result
        assert result["field_mapping_source"] == "config/excel_field_mapping.yaml", result
        assert any(item["field"] == "time_grain" and item["role"] == "time" for item in result["mapped_fields"]), result

        print("S14 Excel smoke test passed")
        print(f"final_score={result['final_score']}")
        print(f"report_file_path={result['report_file_path']}")


if __name__ == "__main__":
    main()
