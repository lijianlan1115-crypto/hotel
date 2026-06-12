"""Data fetching and normalization for the S14 OpenClaw skill.

V4 version: the Excel/database layer passes through all fields required by
calculator.py V4-001~V4-041, C01~C07, and O01~O06.
"""

from __future__ import annotations

import csv
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
EXCEL_MAPPING_CSV = ROOT / "references/excel_field_mapping.csv"

SOURCE_TABLES = [
    "fact_daily_metrics",
    "fact_monthly_metrics",
    "s14_operating_metrics",
    "jd01_bookings",
    "jd04_extensions",
    "fact_room_fee_daily",
    "fact_room_status_snapshot",
]

AVG_FIELDS = {
    "revpar", "adr", "occupancy", "peer_rank",
    "booking_conversion_rate", "exposure_to_view_rate", "peer_exposure_to_view_rate",
    "payment_conversion_rate", "peer_payment_conversion_rate",
    "order_mom", "revenue_mom", "exposure_7d_trend", "views_7d_trend",
    "revpar_3m_avg", "peer_revpar", "peer_adr", "ota_share", "ota_adr", "direct_adr",
    "ad_exposure_share", "entry_coverage_rate", "order_structure_match_rate",
    "sales_speed", "room_type_health_rate", "room_type_revpar_health",
    "price_completeness", "price_band_coverage", "activity_price_consistency",
    "reserved_room_rate", "inventory_health_rate", "room_status_health_rate",
    "competitor_price_power", "promo_roi", "promo_ctr", "promo_cpc",
    "promo_roi_target", "promo_exposure_target", "promo_cpc_target",
    "promo_order_target", "promo_roi_7d_trend", "promo_order_7d_trend",
    "hotel_info_score", "benefit_coverage_rate", "facility_tag_coverage",
    "rating_total", "peer_rating_total", "dianping_rating", "review_reply_rate",
    "bad_review_reply_rate", "bad_review_rate", "bad_review_tag_score",
    "good_keyword_usage_rate", "field_completeness", "action_completion_rate",
    "before_after_compare_ready", "anomaly_review_rate",
    "orders_low_days", "conversion_low_days", "revenue_decline_months",
}

SUM_FIELDS = {
    "room_revenue", "sold_room_nights", "available_room_nights", "remaining_room_nights",
    "paid_orders", "peer_paid_orders", "lost_orders", "lost_amount",
    "exposure", "peer_exposure", "views", "peer_views",
    "ad_exposure", "organic_exposure",
    "promo_amount", "promo_cost", "promo_orders", "promo_clicks", "promo_exposure",
    "review_count", "new_review_count", "unreplied_reviews",
    "completed_actions", "pending_actions",
}

BOOL_FIELDS = {
    "season_or_market_explained", "promo_detail_ready", "good_review_keywords_used",
}

TEXT_FIELDS = {
    "hotel_name", "channel_source", "platform", "time_grain",
    "business_area_tag_status", "poi_status", "facility_tag_status",
    "order_structure_status", "hotel_name_keyword_status", "rights_center_status",
    "invoice_status", "business_travel_status", "public_benefit_traffic_status",
    "image_quality_rating", "video_status", "highlight_status", "room_name_status",
    "room_description_status", "room_selling_point_status", "entry_tag_quality",
    "review_reason",
}

CONTROL_FIELDS = {"hotel_id", "data_date", "period_start_field", "period_end_field"}
RATIO_FIELDS = {field for field in AVG_FIELDS if field.endswith("rate") or field.endswith("_share") or field.endswith("_trend") or field in {"occupancy", "field_completeness", "promo_ctr"}}


class DataFetcher:
    def __init__(self, db_kind: str | None = None, dsn: str | None = None):
        self.db_kind = db_kind or "sqlite"
        self.dsn = dsn

    def fetch_operating_data(self, hotel_id: str, period: dict[str, str], platform: str | None = None) -> dict[str, Any]:
        if not self.dsn:
            raise ValueError("S14 requires db_dsn in OpenClaw config; do not pass upstream Skill output as diagnosis data.")
        if self.db_kind == "sqlite":
            return self._fetch_from_sqlite(hotel_id, period, platform)
        if self.db_kind == "mysql":
            return self._fetch_from_mysql(hotel_id, period, platform)
        raise ValueError(f"unsupported db_kind: {self.db_kind}")

    def fetch_excel_data(self, excel_path: str, hotel_id: str, period: dict[str, str], platform: str | None = None) -> dict[str, Any]:
        records = self._read_excel_records(Path(excel_path))
        mapped = [item for item in (self._map_record(record) for record in records) if item]
        filtered = self._filter_records(mapped, hotel_id, period, platform)
        result = self._aggregate_records(filtered or mapped, hotel_id, period, platform)
        result["source_file_path"] = str(excel_path)
        result["data_source_mode"] = "excel_upload"
        return result

    # ------------------------------------------------------------------
    # Database mode
    # ------------------------------------------------------------------

    def _fetch_from_sqlite(self, hotel_id: str, period: dict[str, str], platform: str | None) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        with sqlite3.connect(str(self.dsn)) as conn:
            conn.row_factory = sqlite3.Row
            tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'").fetchall()}
            for table in SOURCE_TABLES:
                if table not in tables:
                    continue
                try:
                    rows = conn.execute(f"select * from `{table}`").fetchall()
                except Exception:
                    continue
                records.extend(self._map_record(dict(row), source_table=table) for row in rows)
        filtered = self._filter_records([r for r in records if r], hotel_id, period, platform)
        result = self._aggregate_records(filtered or records, hotel_id, period, platform)
        result["data_source_mode"] = "database"
        return result

    def _fetch_from_mysql(self, hotel_id: str, period: dict[str, str], platform: str | None) -> dict[str, Any]:
        try:
            import pymysql  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("MySQL mode requires pymysql in the OpenClaw runtime image.") from exc

        parsed = urlparse(str(self.dsn))
        records: list[dict[str, Any]] = []
        conn = pymysql.connect(
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip("/"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute("show tables")
                table_rows = cursor.fetchall()
                existing = {next(iter(row.values())) if isinstance(row, dict) else row[0] for row in table_rows}
                for table in SOURCE_TABLES:
                    if table not in existing:
                        continue
                    try:
                        cursor.execute(f"select * from `{table}`")
                        rows = cursor.fetchall()
                    except Exception:
                        continue
                    records.extend(self._map_record(dict(row), source_table=table) for row in rows)
        finally:
            conn.close()
        filtered = self._filter_records([r for r in records if r], hotel_id, period, platform)
        result = self._aggregate_records(filtered or records, hotel_id, period, platform)
        result["data_source_mode"] = "database"
        return result

    # ------------------------------------------------------------------
    # Excel mode
    # ------------------------------------------------------------------

    def _read_excel_records(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(f"Excel file not found: {path}")
        if path.suffix.lower() not in {".xlsx", ".xlsm"}:
            raise ValueError("Excel upload must be .xlsx or .xlsm")
        records: list[dict[str, Any]] = []
        for rows in self._read_xlsx_sheets(path).values():
            records.extend(self._records_from_rows(rows))
        return records

    def _read_xlsx_sheets(self, path: Path) -> dict[str, list[list[Any]]]:
        ns = {
            "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
            "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        }
        with ZipFile(path) as zf:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in zf.namelist():
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for item in root.findall("a:si", ns):
                    shared.append("".join(t.text or "" for t in item.findall(".//a:t", ns)))
            workbook = ET.fromstring(zf.read("xl/workbook.xml"))
            rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
            sheets: dict[str, list[list[Any]]] = {}
            for sheet in workbook.findall("a:sheets/a:sheet", ns):
                rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
                target = relmap[rid]
                if not target.startswith("worksheets/"):
                    target = "worksheets/" + target.split("/")[-1]
                sheets[sheet.attrib["name"]] = self._read_xlsx_sheet_rows(zf.read("xl/" + target), shared)
            return sheets

    def _read_xlsx_sheet_rows(self, xml_bytes: bytes, shared: list[str]) -> list[list[Any]]:
        ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        root = ET.fromstring(xml_bytes)
        out: list[list[Any]] = []
        for row in root.findall("a:sheetData/a:row", ns):
            values: dict[int, Any] = {}
            for cell in row.findall("a:c", ns):
                ref = cell.attrib.get("r", "A1")
                idx = self._column_index(ref)
                values[idx] = self._cell_value(cell, shared, ns)
            if values:
                out.append([values.get(i, "") for i in range(max(values) + 1)])
        return out

    def _cell_value(self, cell: ET.Element, shared: list[str], ns: dict[str, str]) -> Any:
        cell_type = cell.attrib.get("t")
        if cell_type == "inlineStr":
            return "".join(t.text or "" for t in cell.findall(".//a:t", ns))
        value = cell.find("a:v", ns)
        if value is None:
            return ""
        raw = value.text or ""
        if cell_type == "s":
            return shared[int(raw)] if raw.isdigit() and int(raw) < len(shared) else raw
        return raw

    def _column_index(self, ref: str) -> int:
        letters = re.sub(r"[^A-Z]", "", ref.upper())
        idx = 0
        for char in letters:
            idx = idx * 26 + (ord(char) - ord("A") + 1)
        return max(idx - 1, 0)

    def _records_from_rows(self, rows: list[list[Any]]) -> list[dict[str, Any]]:
        clean_rows = [[str(cell).strip() if cell is not None else "" for cell in row] for row in rows if any(str(cell).strip() for cell in row)]
        if not clean_rows:
            return []
        alias_map = self._alias_map()
        for idx, row in enumerate(clean_rows):
            if any(alias_map.get(cell) for cell in row):
                headers = row
                return [
                    {headers[i]: data_row[i] if i < len(data_row) else "" for i in range(len(headers))}
                    for data_row in clean_rows[idx + 1:]
                    if any(data_row)
                ]
        if len(clean_rows[0]) >= 2:
            record = {row[0]: row[1] for row in clean_rows if len(row) >= 2 and row[0]}
            return [record] if record else []
        return []

    # ------------------------------------------------------------------
    # Mapping, filtering, aggregation
    # ------------------------------------------------------------------

    def _map_record(self, record: dict[str, Any], source_table: str | None = None) -> dict[str, Any]:
        alias_map = self._alias_map()
        type_map = self._type_map()
        mapped: dict[str, Any] = {}
        if source_table:
            mapped["source_table"] = source_table
        for raw_key, value in record.items():
            standard = alias_map.get(str(raw_key).strip()) or alias_map.get(str(raw_key).strip().lower())
            if not standard:
                continue
            mapped[standard] = self._normalize_value(value, type_map.get(standard, "string"), standard)
        return mapped

    def _alias_map(self) -> dict[str, str]:
        alias_map: dict[str, str] = {}
        if not EXCEL_MAPPING_CSV.exists():
            return alias_map
        with EXCEL_MAPPING_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                standard = str(row.get("标准字段", "")).strip()
                if not standard:
                    continue
                alias_map[standard] = standard
                alias_map[standard.lower()] = standard
                for alias in str(row.get("中文字段别名", "")).split("|"):
                    alias = alias.strip()
                    if alias:
                        alias_map[alias] = standard
                        alias_map[alias.lower()] = standard
        return alias_map

    def _type_map(self) -> dict[str, str]:
        type_map: dict[str, str] = {}
        if not EXCEL_MAPPING_CSV.exists():
            return type_map
        with EXCEL_MAPPING_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("标准字段"):
                    type_map[str(row["标准字段"]).strip()] = str(row.get("类型", "string")).strip()
        return type_map

    def _normalize_value(self, value: Any, value_type: str, field: str) -> Any:
        if value in (None, ""):
            return None
        if value_type in {"number", "ratio"} or field in AVG_FIELDS or field in SUM_FIELDS:
            return self._to_float(value, ratio=value_type == "ratio" or field in RATIO_FIELDS)
        if value_type == "boolean" or field in BOOL_FIELDS:
            return str(value).strip().lower() in {"1", "true", "yes", "是", "已补齐", "完整", "正常", "有"}
        if value_type == "date" or field in {"data_date", "period_start_field", "period_end_field"}:
            return self._to_date_text(value)
        return str(value).strip()

    def _to_float(self, value: Any, ratio: bool = False) -> float | None:
        if value in (None, ""):
            return None
        text = str(value).strip().replace(",", "")
        if text.endswith("%"):
            try:
                return float(text[:-1]) / 100
            except ValueError:
                return None
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None
        number = float(match.group())
        return number / 100 if ratio and number > 1 else number

    def _to_date_text(self, value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
            try:
                return datetime.strptime(text[:10], fmt).date().isoformat()
            except ValueError:
                pass
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            return (date(1899, 12, 30) + timedelta(days=int(float(text)))).isoformat()
        return text

    def _filter_records(self, records: list[dict[str, Any]], hotel_id: str, period: dict[str, str], platform: str | None) -> list[dict[str, Any]]:
        start = period["start"]
        end = period["end"]
        filtered: list[dict[str, Any]] = []
        for record in records:
            if record.get("hotel_id") and str(record["hotel_id"]) != hotel_id:
                continue
            if not self._is_multi_platform(platform) and record.get("platform") and str(record["platform"]) not in {str(platform), self._platform_name(str(platform))}:
                continue
            record_start = str(record.get("period_start_field") or record.get("data_date") or "")
            record_end = str(record.get("period_end_field") or record.get("data_date") or "")
            if record_start and record_end and (record_end < start or record_start > end):
                continue
            filtered.append(record)
        return filtered

    def _aggregate_records(self, records: list[dict[str, Any]], hotel_id: str, period: dict[str, str], platform: str | None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "hotel_id": hotel_id,
            "platform": platform,
            "channel_source": self._platform_name(str(platform)) if platform else None,
            "period_start": period["start"],
            "period_end": period["end"],
            "source_row_count": len(records),
        }
        for field in AVG_FIELDS:
            values = [record.get(field) for record in records if isinstance(record.get(field), (int, float))]
            if values:
                result[field] = sum(values) / len(values)
        for field in SUM_FIELDS:
            values = [record.get(field) for record in records if isinstance(record.get(field), (int, float))]
            if values:
                result[field] = sum(values)
        for field in BOOL_FIELDS:
            values = [record.get(field) for record in records if record.get(field) not in (None, "")]
            if values:
                result[field] = any(bool(value) for value in values)
        for field in TEXT_FIELDS:
            value = next((record.get(field) for record in records if record.get(field) not in (None, "")), None)
            if value is not None:
                result[field] = value
        if not result.get("channel_source") and result.get("platform"):
            result["channel_source"] = self._platform_name(str(result["platform"]))
        if result.get("promo_cost") and not result.get("promo_roi"):
            result["promo_roi"] = (result.get("promo_amount") or 0) / result["promo_cost"]
        if result.get("promo_exposure") and result.get("promo_clicks") and not result.get("promo_ctr"):
            result["promo_ctr"] = result["promo_clicks"] / result["promo_exposure"]
        if result.get("promo_clicks") and result.get("promo_cost") and not result.get("promo_cpc"):
            result["promo_cpc"] = result["promo_cost"] / result["promo_clicks"]
        if result.get("exposure") and result.get("views") and not result.get("exposure_to_view_rate"):
            result["exposure_to_view_rate"] = result["views"] / result["exposure"]
        if result.get("available_room_nights") and result.get("sold_room_nights") and not result.get("sales_speed"):
            result["sales_speed"] = result["sold_room_nights"] / result["available_room_nights"]
        result["time_grain"] = result.get("time_grain") or "period"
        return result

    def _is_multi_platform(self, platform: str | None) -> bool:
        return str(platform or "").lower() in {"", "all", "multi", "multi_channel", "多渠道", "全渠道"}

    def _platform_name(self, platform: str) -> str:
        return {
            "fliggy": "飞猪",
            "meituan": "美团",
            "ctrip": "携程",
            "qunar": "去哪儿",
            "douyin": "抖音",
            "multi": "多渠道",
            "all": "多渠道",
            "multi_channel": "多渠道",
        }.get(platform, platform)
