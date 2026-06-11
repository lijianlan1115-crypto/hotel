"""Data fetching and normalization for the S14 OpenClaw skill."""

from __future__ import annotations

import csv
import sqlite3
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
EXCEL_MAPPING_CSV = ROOT / "references/excel_field_mapping.csv"


SOURCE_TABLES: dict[str, dict[str, Any]] = {
    "fact_daily_metrics": {
        "time_grain": "daily",
        "date_aliases": ["data_date", "biz_date", "stat_date", "date", "日期", "营业日期", "业务日期"],
        "hotel_aliases": ["hotel_id", "hotel_code", "酒店ID", "门店ID"],
        "platform_aliases": ["platform", "channel", "ota_channel", "channel_source", "渠道", "平台", "OTA渠道"],
        "field_aliases": {
            "hotel_name": ["hotel_name", "酒店名称", "门店名称"],
            "channel_source": ["channel_source", "渠道来源", "渠道名称", "渠道"],
            "revpar": ["revpar", "RevPAR", "平均可售房收入"],
            "adr": ["adr", "ADR", "平均房价", "客单价"],
            "occupancy": ["occupancy", "occ", "出租率", "入住率"],
            "room_revenue": ["room_revenue", "revenue", "gmv", "间夜收入", "客房收入", "订单金额"],
            "sold_room_nights": ["sold_room_nights", "room_nights", "night_count", "入住间夜", "售出间夜", "间夜数"],
            "available_room_nights": ["available_room_nights", "available_rooms", "可售间夜", "可售房量"],
            "exposure": ["exposure", "曝光量", "列表曝光", "展示次数"],
            "views": ["views", "浏览量", "详情浏览", "访客数", "UV"],
            "peer_rank": ["peer_rank", "竞争圈排名", "同行排名"],
            "booking_conversion_rate": ["booking_conversion_rate", "booking_rate", "预订转化率", "浏览-预订转化"],
            "payment_conversion_rate": ["payment_conversion_rate", "pay_rate", "支付转化率", "浏览-支付转化"],
            "lost_orders": ["lost_orders", "流失订单", "取消订单数"],
            "lost_amount": ["lost_amount", "流失金额", "取消金额"],
            "promo_amount": ["promo_amount", "推广订单金额", "推广成交金额"],
            "promo_cost": ["promo_cost", "推广花费", "广告消耗"],
            "promo_roi": ["promo_roi", "ROI", "推广ROI"],
            "promo_detail_ready": ["promo_detail_ready", "推广明细完整", "推广明细是否完整", "是否有推广明细"],
            "rating_total": ["rating_total", "平台评分", "评分"],
            "bad_review_rate": ["bad_review_rate", "差评率", "低分率"],
            "unreplied_reviews": ["unreplied_reviews", "未回复评价数", "未回复评论"],
            "field_completeness": ["field_completeness", "字段完整度", "数据完整度"],
        },
    },
    "fact_monthly_metrics": {
        "time_grain": "monthly",
        "date_aliases": ["month", "stat_month", "data_month", "period_start_date", "月份", "统计月份"],
        "period_end_aliases": ["period_end_date", "month_end", "结束日期", "周期结束"],
        "hotel_aliases": ["hotel_id", "hotel_code", "酒店ID", "门店ID"],
        "platform_aliases": ["platform", "channel", "ota_channel", "channel_source", "渠道", "平台", "OTA渠道"],
        "field_aliases": {},
    },
    "jd01_bookings": {
        "time_grain": "booking",
        "date_aliases": ["booking_date", "order_date", "biz_date", "created_date", "data_date", "预订日期", "订单日期"],
        "hotel_aliases": ["hotel_id", "hotel_code", "酒店ID", "门店ID"],
        "platform_aliases": ["platform", "channel", "ota_channel", "channel_source", "渠道", "平台", "OTA渠道"],
        "field_aliases": {
            "hotel_name": ["hotel_name", "酒店名称", "门店名称"],
            "channel_source": ["channel_source", "渠道来源", "渠道名称", "渠道"],
            "room_revenue": ["room_revenue", "pay_amount", "order_amount", "订单金额", "实付金额", "间夜收入"],
            "sold_room_nights": ["sold_room_nights", "room_nights", "night_count", "间夜数", "入住间夜"],
            "lost_orders": ["lost_orders", "cancel_count", "取消订单数", "流失订单"],
            "lost_amount": ["lost_amount", "cancel_amount", "取消金额", "流失金额"],
        },
    },
    "jd04_extensions": {
        "time_grain": "event",
        "date_aliases": ["data_date", "biz_date", "created_date", "日期"],
        "hotel_aliases": ["hotel_id", "hotel_code", "酒店ID", "门店ID"],
        "platform_aliases": ["platform", "channel", "ota_channel", "channel_source", "渠道", "平台", "OTA渠道"],
        "field_aliases": {
            "hotel_name": ["hotel_name", "酒店名称", "门店名称"],
            "channel_source": ["channel_source", "渠道来源", "渠道名称", "渠道"],
            "image_quality_rating": ["image_quality_rating", "图片质量评级", "图片质量"],
            "video_status": ["video_status", "视频状态", "视频"],
            "room_selling_point_status": ["room_selling_point_status", "房型卖点状态", "卖点状态"],
            "entry_tag_quality": ["entry_tag_quality", "入口标签质量", "标签质量"],
            "completed_actions": ["completed_actions", "已完成动作", "已整改事项"],
            "pending_actions": ["pending_actions", "待处理动作", "待整改事项"],
            "review_reason": ["review_reason", "复盘原因", "问题原因"],
        },
    },
    "fact_room_fee_daily": {
        "time_grain": "daily",
        "date_aliases": ["data_date", "biz_date", "stat_date", "日期", "营业日期"],
        "hotel_aliases": ["hotel_id", "hotel_code", "酒店ID", "门店ID"],
        "platform_aliases": ["platform", "channel", "ota_channel", "channel_source", "渠道", "平台", "OTA渠道"],
        "field_aliases": {
            "hotel_name": ["hotel_name", "酒店名称", "门店名称"],
            "channel_source": ["channel_source", "渠道来源", "渠道名称", "渠道"],
            "adr": ["adr", "ADR", "平均房价", "售卖价", "房费"],
            "price_completeness": ["price_completeness", "价格完整度", "有价率"],
        },
    },
    "fact_room_status_snapshot": {
        "time_grain": "snapshot",
        "date_aliases": ["snapshot_date", "data_date", "biz_date", "stat_date", "日期", "快照日期"],
        "hotel_aliases": ["hotel_id", "hotel_code", "酒店ID", "门店ID"],
        "platform_aliases": ["platform", "channel", "ota_channel", "channel_source", "渠道", "平台", "OTA渠道"],
        "field_aliases": {
            "hotel_name": ["hotel_name", "酒店名称", "门店名称"],
            "channel_source": ["channel_source", "渠道来源", "渠道名称", "渠道"],
            "available_room_nights": ["available_room_nights", "available_rooms", "可售间夜", "可售房量"],
            "inventory_health_rate": ["inventory_health_rate", "库存健康度", "房态健康度"],
            "room_type_health_rate": ["room_type_health_rate", "房型健康度", "房型完整度"],
        },
    },
}

SOURCE_TABLES["fact_monthly_metrics"]["field_aliases"] = SOURCE_TABLES["fact_daily_metrics"]["field_aliases"]


class DataFetcher:
    def __init__(self, db_kind: str | None = None, dsn: str | None = None):
        self.db_kind = db_kind or "sqlite"
        self.dsn = dsn

    def fetch_operating_data(self, hotel_id: str, period: dict[str, str], platform: str | None = None) -> dict[str, Any]:
        """Fetch normalized operating metrics.

        S14 is independent: runtime reads all diagnosis facts from its own
        database tables and must not consume other Skill outputs as inputs.
        """
        if not self.dsn:
            raise ValueError("S14 requires db_dsn in OpenClaw config; do not pass upstream Skill output as diagnosis data.")
        if self.db_kind == "sqlite":
            return self._fetch_from_sqlite(hotel_id, period, platform)
        if self.db_kind == "mysql":
            return self._fetch_from_mysql(hotel_id, period, platform)
        raise ValueError(f"unsupported db_kind: {self.db_kind}")

    def fetch_excel_data(self, excel_path: str, hotel_id: str, period: dict[str, str], platform: str | None = None) -> dict[str, Any]:
        """Fetch and normalize facts from an uploaded Excel workbook.

        Excel files may use Chinese headers. Header aliases are controlled by
        references/excel_field_mapping.csv and config/excel_field_mapping.yaml.
        """
        records = self._read_excel_records(Path(excel_path))
        mapped_records = [record for record in (self._map_excel_record(item) for item in records) if record]
        filtered = self._filter_records(mapped_records, hotel_id, period, platform)
        result = self._aggregate_records(filtered or mapped_records, hotel_id, period, platform)
        result["source_file_path"] = str(excel_path)
        result["data_source_mode"] = "excel_upload"
        return result

    def _fetch_from_sqlite(self, hotel_id: str, period: dict[str, str], platform: str | None) -> dict[str, Any]:
        with sqlite3.connect(str(self.dsn)) as conn:
            conn.row_factory = sqlite3.Row
            records = self._fetch_hotel_pricing_records(conn, "sqlite", hotel_id, period, platform)
            if records:
                return self._aggregate_hotel_pricing_records(records, hotel_id, period, platform)
            query = self._period_aggregate_query("?")
            try:
                row = conn.execute(query, (hotel_id, period["start"], period["end"], platform, platform)).fetchone()
            except Exception:
                row = None
        return self._normalize_row(row, hotel_id, period, platform)

    def _fetch_from_mysql(self, hotel_id: str, period: dict[str, str], platform: str | None) -> dict[str, Any]:
        try:
            import pymysql  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("MySQL mode requires pymysql in the OpenClaw runtime image.") from exc

        parsed = urlparse(str(self.dsn))
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
            records = self._fetch_hotel_pricing_records(conn, "mysql", hotel_id, period, platform)
            if records:
                return self._aggregate_hotel_pricing_records(records, hotel_id, period, platform)
            query = self._period_aggregate_query("%s")
            try:
                with conn.cursor() as cursor:
                    cursor.execute(query, (hotel_id, period["start"], period["end"], platform, platform))
                    row = cursor.fetchone()
            except Exception:
                row = None
        finally:
            conn.close()
        return self._normalize_row(row, hotel_id, period, platform)

    def _fetch_hotel_pricing_records(self, conn: Any, db_kind: str, hotel_id: str, period: dict[str, str], platform: str | None) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for table_name, spec in SOURCE_TABLES.items():
            columns = self._table_columns(conn, db_kind, table_name)
            if not columns:
                continue
            records.extend(self._fetch_source_table(conn, db_kind, table_name, spec, columns, hotel_id, period, platform))
        return records

    def _table_columns(self, conn: Any, db_kind: str, table_name: str) -> list[str]:
        try:
            if db_kind == "sqlite":
                rows = conn.execute(f"pragma table_info(`{table_name}`)").fetchall()
                return [row[1] for row in rows]
            with conn.cursor() as cursor:
                cursor.execute(f"show columns from `{table_name}`")
                rows = cursor.fetchall()
            return [row["Field"] if isinstance(row, dict) else row[0] for row in rows]
        except Exception:
            return []

    def _fetch_source_table(
        self,
        conn: Any,
        db_kind: str,
        table_name: str,
        spec: dict[str, Any],
        columns: list[str],
        hotel_id: str,
        period: dict[str, str],
        platform: str | None,
    ) -> list[dict[str, Any]]:
        # Handle wide table format (metric_name + metric_value)
        if table_name == "fact_daily_metrics" and "metric_name" in columns and "metric_value" in columns:
            return self._fetch_wide_table(conn, db_kind, table_name, spec, hotel_id, period, platform)
        if table_name == "fact_monthly_metrics" and "metric_name" in columns and "metric_value" in columns:
            return self._fetch_wide_table(conn, db_kind, table_name, spec, hotel_id, period, platform)
        column_map = {column.lower(): column for column in columns}
        hotel_col = self._first_column(column_map, spec.get("hotel_aliases", []))
        date_col = self._first_column(column_map, spec.get("date_aliases", []))
        period_end_col = self._first_column(column_map, spec.get("period_end_aliases", []))
        platform_col = self._first_column(column_map, spec.get("platform_aliases", []))

        selected = {column for column in (hotel_col, date_col, period_end_col, platform_col) if column}
        for aliases in spec.get("field_aliases", {}).values():
            found = self._first_column(column_map, aliases)
            if found:
                selected.add(found)
        if not selected:
            return []

        placeholder = "?" if db_kind == "sqlite" else "%s"
        where: list[str] = []
        params: list[Any] = []
        if hotel_col:
            where.append(f"`{hotel_col}` = {placeholder}")
            params.append(hotel_id)
        if date_col and period_end_col:
            where.append(f"`{period_end_col}` >= {placeholder} and `{date_col}` <= {placeholder}")
            params.extend([period["start"], period["end"]])
        elif date_col:
            where.append(f"`{date_col}` >= {placeholder} and `{date_col}` <= {placeholder}")
            params.extend([period["start"], period["end"]])
        if platform and platform != "multi" and platform_col:
            where.append(f"`{platform_col}` in ({placeholder}, {placeholder})")
            params.extend([platform, self._platform_name(platform)])

        sql = f"select {', '.join(f'`{column}`' for column in sorted(selected))} from `{table_name}`"
        if where:
            sql += " where " + " and ".join(where)

        try:
            if db_kind == "sqlite":
                rows = conn.execute(sql, params).fetchall()
            else:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    rows = cursor.fetchall()
        except Exception:
            return []

        return [self._map_source_row(dict(row), table_name, spec, column_map, date_col, period_end_col, platform_col) for row in rows]

    def _fetch_wide_table(
        self,
        conn: Any,
        db_kind: str,
        table_name: str,
        spec: dict[str, Any],
        hotel_id: str,
        period: dict[str, str],
        platform: str | None,
    ) -> list[dict[str, Any]]:
        """Fetch and transform wide table format (metric_name + metric_value) to narrow format."""
        placeholder = "?" if db_kind == "sqlite" else "%s"
        
        # 指标名称到字段名的映射
        metric_mapping = {
            "revpar": "revpar",
            "RevPAR": "revpar",
            "RevPar": "revpar",
            "平均可售房收入": "revpar",
            "adr": "adr",
            "ADR": "adr",
            "平均房价": "adr",
            "客单价": "adr",
            "房费": "adr",
            "occupancy": "occupancy",
            "occ": "occupancy",
            "出租率": "occupancy",
            "入住率": "occupancy",
            "过夜房出租率": "occupancy",
            "过夜房出租率(扣自用房)": "occupancy",
            "客房数": "available_room_nights",
            "过夜房": "sold_room_nights",
            "间夜数": "sold_room_nights",
            "现付账房费": "room_revenue",
            "曝光量": "exposure",
            "列表曝光": "exposure",
            "展示次数": "exposure",
            "浏览量": "views",
            "详情浏览": "views",
            "访客数": "views",
            "UV": "views",
            "订单金额": "room_revenue",
            "间夜收入": "room_revenue",
            "客房收入": "room_revenue",
            "revenue": "room_revenue",
            "gmv": "room_revenue",
            "room_revenue": "room_revenue",
            "售出间夜": "sold_room_nights",
            "入住间夜": "sold_room_nights",
            "room_nights": "sold_room_nights",
            "sold_room_nights": "sold_room_nights",
            "可售间夜": "available_room_nights",
            "可售房量": "available_room_nights",
            "available_room_nights": "available_room_nights",
            "竞争圈排名": "peer_rank",
            "同行排名": "peer_rank",
            "peer_rank": "peer_rank",
            "预订转化率": "booking_conversion_rate",
            "浏览-预订转化": "booking_conversion_rate",
            "booking_conversion_rate": "booking_conversion_rate",
            "支付转化率": "payment_conversion_rate",
            "浏览-支付转化": "payment_conversion_rate",
            "payment_conversion_rate": "payment_conversion_rate",
            "流失订单": "lost_orders",
            "取消订单数": "lost_orders",
            "lost_orders": "lost_orders",
            "流失金额": "lost_amount",
            "取消金额": "lost_amount",
            "lost_amount": "lost_amount",
            "推广订单金额": "promo_amount",
            "推广成交金额": "promo_amount",
            "promo_amount": "promo_amount",
            "推广花费": "promo_cost",
            "广告消耗": "promo_cost",
            "promo_cost": "promo_cost",
            "ROI": "promo_roi",
            "推广ROI": "promo_roi",
            "promo_roi": "promo_roi",
            "平台评分": "rating_total",
            "评分": "rating_total",
            "rating_total": "rating_total",
            "差评率": "bad_review_rate",
            "低分率": "bad_review_rate",
            "bad_review_rate": "bad_review_rate",
            "未回复评价数": "unreplied_reviews",
            "未回复评论": "unreplied_reviews",
            "unreplied_reviews": "unreplied_reviews",
            "字段完整度": "field_completeness",
            "数据完整度": "field_completeness",
            "field_completeness": "field_completeness",
            "价格完整度": "price_completeness",
            "有价率": "price_completeness",
            "price_completeness": "price_completeness",
            "库存健康度": "inventory_health_rate",
            "房态健康度": "inventory_health_rate",
            "inventory_health_rate": "inventory_health_rate",
            "房型健康度": "room_type_health_rate",
            "房型完整度": "room_type_health_rate",
            "room_type_health_rate": "room_type_health_rate",
            "图片质量评级": "image_quality_rating",
            "图片质量": "image_quality_rating",
            "image_quality_rating": "image_quality_rating",
            "视频状态": "video_status",
            "video_status": "video_status",
            "房型卖点状态": "room_selling_point_status",
            "卖点状态": "room_selling_point_status",
            "room_selling_point_status": "room_selling_point_status",
            "入口标签质量": "entry_tag_quality",
            "标签质量": "entry_tag_quality",
            "entry_tag_quality": "entry_tag_quality",
            "已完成动作": "completed_actions",
            "已整改事项": "completed_actions",
            "completed_actions": "completed_actions",
            "待处理动作": "pending_actions",
            "待整改事项": "pending_actions",
            "pending_actions": "pending_actions",
            "复盘原因": "review_reason",
            "问题原因": "review_reason",
            "review_reason": "review_reason",
        }

        sql = f"""
            SELECT business_date, hotel_name, metric_name, metric_value
            FROM `{table_name}`
            WHERE business_date >= {placeholder} AND business_date <= {placeholder}
        """
        params = [period["start"], period["end"]]

        try:
            if db_kind == "sqlite":
                rows = conn.execute(sql, params).fetchall()
            else:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    rows = cursor.fetchall()
        except Exception:
            return []

        # 按日期分组，将宽表转换为窄表
        by_date: dict[str, dict[str, Any]] = {}
        for row in rows:
            row_dict = dict(row) if isinstance(row, dict) else {
                "business_date": row[0],
                "hotel_name": row[1],
                "metric_name": row[2],
                "metric_value": row[3]
            }
            date_key = str(row_dict.get("business_date", ""))
            if date_key not in by_date:
                by_date[date_key] = {
                    "source_table": table_name,
                    "time_grain": spec.get("time_grain"),
                    "data_date": date_key,
                    "period_start_field": date_key,
                    "hotel_name": row_dict.get("hotel_name"),
                }
            
            metric_name = row_dict.get("metric_name", "")
            metric_value = row_dict.get("metric_value")
            field_name = metric_mapping.get(metric_name)
            if field_name and metric_value is not None:
                # Convert Decimal, int, float to float
                if isinstance(metric_value, (int, float)) or hasattr(metric_value, 'as_tuple'):  # Check for Decimal
                    val = float(metric_value)
                    # Occupancy rates are stored as percentages (e.g., 79.88 = 79.88%), convert to decimal
                    if field_name == "occupancy" and val > 1:
                        val = val / 100.0
                    by_date[date_key][field_name] = val
                else:
                    by_date[date_key][field_name] = metric_value

        return list(by_date.values())

    def _first_column(self, column_map: dict[str, str], aliases: list[str]) -> str | None:
        for alias in aliases:
            found = column_map.get(str(alias).lower())
            if found:
                return found
        return None

    def _map_source_row(
        self,
        row: dict[str, Any],
        table_name: str,
        spec: dict[str, Any],
        column_map: dict[str, str],
        date_col: str | None,
        period_end_col: str | None,
        platform_col: str | None,
    ) -> dict[str, Any]:
        mapped: dict[str, Any] = {
            "source_table": table_name,
            "time_grain": spec.get("time_grain"),
        }
        if date_col and row.get(date_col) not in (None, ""):
            mapped["data_date"] = self._to_date_text(row.get(date_col))
            mapped["period_start_field"] = mapped["data_date"]
        if period_end_col and row.get(period_end_col) not in (None, ""):
            mapped["period_end_field"] = self._to_date_text(row.get(period_end_col))
        if platform_col and row.get(platform_col) not in (None, ""):
            mapped["platform"] = str(row.get(platform_col)).strip()

        type_map = self._excel_type_map()
        for target, aliases in spec.get("field_aliases", {}).items():
            column = self._first_column(column_map, aliases)
            if not column or row.get(column) in (None, ""):
                continue
            mapped[target] = self._normalize_excel_value(row.get(column), type_map.get(target, "string"))
        return mapped

    def _aggregate_hotel_pricing_records(self, records: list[dict[str, Any]], hotel_id: str, period: dict[str, str], platform: str | None) -> dict[str, Any]:
        by_table: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            by_table.setdefault(str(record.get("source_table")), []).append(record)

        table_metrics = {
            table: self._aggregate_records(items, hotel_id, period, platform)
            for table, items in by_table.items()
        }
        result: dict[str, Any] = {
            "hotel_id": hotel_id,
            "platform": platform,
            "channel_source": self._platform_name(platform) if platform else None,
            "period_start": period["start"],
            "period_end": period["end"],
            "time_grain": "mixed",
            "source_row_count": len(records),
            "source_tables": sorted(by_table),
            "data_source_mode": "database",
        }

        priority = {
            "hotel_name": ["fact_daily_metrics", "fact_monthly_metrics", "jd01_bookings", "jd04_extensions", "fact_room_fee_daily", "fact_room_status_snapshot"],
            "channel_source": ["fact_daily_metrics", "fact_monthly_metrics", "jd01_bookings", "jd04_extensions", "fact_room_fee_daily", "fact_room_status_snapshot"],
            "revpar": ["fact_daily_metrics", "fact_monthly_metrics"],
            "adr": ["fact_daily_metrics", "fact_room_fee_daily", "fact_monthly_metrics"],
            "occupancy": ["fact_daily_metrics", "fact_monthly_metrics"],
            "room_revenue": ["fact_daily_metrics", "jd01_bookings", "fact_monthly_metrics"],
            "sold_room_nights": ["fact_daily_metrics", "jd01_bookings", "fact_monthly_metrics"],
            "available_room_nights": ["fact_room_status_snapshot", "fact_daily_metrics", "fact_monthly_metrics"],
            "exposure": ["fact_daily_metrics", "fact_monthly_metrics"],
            "views": ["fact_daily_metrics", "fact_monthly_metrics"],
            "peer_rank": ["fact_daily_metrics", "fact_monthly_metrics"],
            "booking_conversion_rate": ["fact_daily_metrics", "fact_monthly_metrics"],
            "payment_conversion_rate": ["fact_daily_metrics", "fact_monthly_metrics"],
            "lost_orders": ["fact_daily_metrics", "jd01_bookings", "fact_monthly_metrics"],
            "lost_amount": ["fact_daily_metrics", "jd01_bookings", "fact_monthly_metrics"],
            "price_completeness": ["fact_room_fee_daily", "fact_daily_metrics", "fact_monthly_metrics"],
            "inventory_health_rate": ["fact_room_status_snapshot", "fact_daily_metrics", "fact_monthly_metrics"],
            "room_type_health_rate": ["fact_room_status_snapshot", "fact_daily_metrics", "fact_monthly_metrics"],
            "promo_amount": ["fact_daily_metrics", "fact_monthly_metrics"],
            "promo_cost": ["fact_daily_metrics", "fact_monthly_metrics"],
            "promo_roi": ["fact_daily_metrics", "fact_monthly_metrics"],
            "promo_detail_ready": ["fact_daily_metrics", "fact_monthly_metrics"],
            "rating_total": ["fact_daily_metrics", "fact_monthly_metrics"],
            "bad_review_rate": ["fact_daily_metrics", "fact_monthly_metrics"],
            "unreplied_reviews": ["fact_daily_metrics", "fact_monthly_metrics"],
            "field_completeness": ["fact_daily_metrics", "fact_monthly_metrics"],
            "image_quality_rating": ["jd04_extensions"],
            "video_status": ["jd04_extensions"],
            "room_selling_point_status": ["jd04_extensions"],
            "entry_tag_quality": ["jd04_extensions"],
            "completed_actions": ["jd04_extensions"],
            "pending_actions": ["jd04_extensions"],
            "review_reason": ["jd04_extensions"],
        }
        for field, tables in priority.items():
            for table in tables:
                value = table_metrics.get(table, {}).get(field)
                if value not in (None, "", [], {}):
                    result[field] = value
                    break
        if result.get("promo_cost") and not result.get("promo_roi"):
            result["promo_roi"] = (result.get("promo_amount") or 0) / result["promo_cost"]
        return result

    def _period_aggregate_query(self, placeholder: str) -> str:
        return f"""
            select
              hotel_id,
              platform,
              max(hotel_name) as hotel_name,
              max(channel_source) as channel_source,
              min(coalesce(period_start_date, data_date)) as period_start,
              max(coalesce(period_end_date, data_date)) as period_end,
              max(time_grain) as time_grain,
              avg(revpar) as revpar,
              avg(adr) as adr,
              avg(occupancy) as occupancy,
              sum(room_revenue) as room_revenue,
              sum(sold_room_nights) as sold_room_nights,
              sum(available_room_nights) as available_room_nights,
              sum(exposure) as exposure,
              sum(views) as views,
              avg(peer_rank) as peer_rank,
              avg(booking_conversion_rate) as booking_conversion_rate,
              avg(payment_conversion_rate) as payment_conversion_rate,
              sum(lost_orders) as lost_orders,
              sum(lost_amount) as lost_amount,
              avg(price_completeness) as price_completeness,
              avg(inventory_health_rate) as inventory_health_rate,
              avg(room_type_health_rate) as room_type_health_rate,
              sum(promo_amount) as promo_amount,
              sum(promo_cost) as promo_cost,
              case
                when sum(promo_cost) is not null and sum(promo_cost) > 0
                then sum(promo_amount) / sum(promo_cost)
                else avg(promo_roi)
              end as promo_roi,
              max(promo_detail_ready) as promo_detail_ready,
              max(image_quality_rating) as image_quality_rating,
              max(video_status) as video_status,
              max(room_selling_point_status) as room_selling_point_status,
              max(entry_tag_quality) as entry_tag_quality,
              avg(rating_total) as rating_total,
              avg(bad_review_rate) as bad_review_rate,
              sum(unreplied_reviews) as unreplied_reviews,
              max(completed_actions) as completed_actions,
              max(pending_actions) as pending_actions,
              max(review_reason) as review_reason,
              avg(field_completeness) as field_completeness,
              count(*) as source_row_count
            from s14_operating_metrics
            where hotel_id = {placeholder}
              and coalesce(period_end_date, data_date) >= {placeholder}
              and coalesce(period_start_date, data_date) <= {placeholder}
              and ({placeholder} is null or platform = {placeholder})
            group by hotel_id, platform
            order by source_row_count desc
            limit 1
        """

    def _normalize_row(self, row: Any, hotel_id: str, period: dict[str, str], platform: str | None) -> dict[str, Any]:
        if not row:
            return {
                "hotel_id": hotel_id,
                "period_start": period["start"],
                "period_end": period["end"],
                "platform": platform,
                "source_row_count": 0,
            }
        data = dict(row)
        data.setdefault("hotel_id", hotel_id)
        data.setdefault("period_start", period["start"])
        data.setdefault("period_end", period["end"])
        data.setdefault("platform", platform)
        data.setdefault("data_source_mode", "database")
        return data

    def _read_excel_records(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(f"Excel file not found: {path}")
        suffix = path.suffix.lower()
        if suffix not in {".xlsx", ".xlsm"}:
            raise ValueError("Excel upload must be .xlsx or .xlsm")

        sheets = self._read_xlsx_sheets(path)
        records: list[dict[str, Any]] = []
        for _sheet_name, rows in sheets.items():
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
                name = sheet.attrib["name"]
                rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
                target = relmap[rid]
                if not target.startswith("worksheets/"):
                    target = "worksheets/" + target.split("/")[-1]
                rows = self._read_xlsx_sheet_rows(zf.read("xl/" + target), shared)
                sheets[name] = rows
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
                max_idx = max(values)
                out.append([values.get(i, "") for i in range(max_idx + 1)])
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

        records: list[dict[str, Any]] = []
        mapping = self._excel_alias_map()
        for idx, row in enumerate(clean_rows):
            mapped_headers = [mapping.get(cell, "") for cell in row]
            if any(mapped_headers):
                headers = row
                for data_row in clean_rows[idx + 1:]:
                    record = {headers[i]: data_row[i] if i < len(data_row) else "" for i in range(len(headers))}
                    records.append(record)
                return records

        if len(clean_rows[0]) >= 2:
            record: dict[str, Any] = {}
            for row in clean_rows:
                if len(row) >= 2 and row[0]:
                    record[row[0]] = row[1]
            return [record] if record else []
        return []

    def _map_excel_record(self, record: dict[str, Any]) -> dict[str, Any]:
        alias_map = self._excel_alias_map()
        type_map = self._excel_type_map()
        mapped: dict[str, Any] = {}
        for raw_key, value in record.items():
            key = alias_map.get(str(raw_key).strip())
            if not key:
                continue
            mapped[key] = self._normalize_excel_value(value, type_map.get(key, "string"))
        return mapped

    def _excel_alias_map(self) -> dict[str, str]:
        alias_map: dict[str, str] = {}
        if not EXCEL_MAPPING_CSV.exists():
            return alias_map
        with EXCEL_MAPPING_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                standard = row["标准字段"]
                alias_map[standard] = standard
                for alias in row["中文字段别名"].split("|"):
                    alias_map[alias.strip()] = standard
        return alias_map

    def _excel_type_map(self) -> dict[str, str]:
        type_map: dict[str, str] = {}
        if not EXCEL_MAPPING_CSV.exists():
            return type_map
        with EXCEL_MAPPING_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                type_map[row["标准字段"]] = row["类型"]
        return type_map

    def _normalize_excel_value(self, value: Any, value_type: str) -> Any:
        if value in (None, ""):
            return None
        if value_type in {"number", "ratio"}:
            return self._to_float(value, ratio=value_type == "ratio")
        if value_type == "boolean":
            return str(value).strip().lower() in {"1", "true", "yes", "是", "已补齐", "完整"}
        if value_type == "date":
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
        if ratio and number > 1:
            return number / 100
        return number

    def _to_date_text(self, value: Any) -> str | None:
        text = str(value).strip()
        if not text:
            return None
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
            if platform and platform != "multi" and record.get("platform") and str(record["platform"]) not in {platform, self._platform_name(platform)}:
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
            "channel_source": self._platform_name(platform) if platform else None,
            "period_start": period["start"],
            "period_end": period["end"],
            "source_row_count": len(records),
        }
        avg_fields = {"revpar", "adr", "occupancy", "peer_rank", "booking_conversion_rate", "payment_conversion_rate", "price_completeness", "inventory_health_rate", "room_type_health_rate", "rating_total", "bad_review_rate", "field_completeness"}
        sum_fields = {"room_revenue", "sold_room_nights", "available_room_nights", "exposure", "views", "lost_orders", "lost_amount", "promo_amount", "promo_cost", "unreplied_reviews"}
        bool_fields = {"promo_detail_ready"}
        text_fields = {"hotel_name", "channel_source", "time_grain", "image_quality_rating", "video_status", "room_selling_point_status", "entry_tag_quality", "completed_actions", "pending_actions", "review_reason"}

        for field in avg_fields:
            values = [record.get(field) for record in records if isinstance(record.get(field), (int, float))]
            if values:
                result[field] = sum(values) / len(values)
        for field in sum_fields:
            values = [record.get(field) for record in records if isinstance(record.get(field), (int, float))]
            if values:
                result[field] = sum(values)
        for field in bool_fields:
            values = [record.get(field) for record in records if record.get(field) not in (None, "")]
            if values:
                result[field] = any(bool(value) for value in values)
        for field in text_fields:
            value = next((record.get(field) for record in records if record.get(field) not in (None, "")), None)
            if value is not None:
                result[field] = value
        if not result.get("channel_source") and result.get("platform"):
            result["channel_source"] = self._platform_name(str(result["platform"]))
        if result.get("promo_cost"):
            result["promo_roi"] = (result.get("promo_amount") or 0) / result["promo_cost"]
        result["time_grain"] = result.get("time_grain") or "period"
        return result

    def _platform_name(self, platform: str) -> str:
        return {
            "fliggy": "飞猪",
            "meituan": "美团",
            "ctrip": "携程",
            "qunar": "去哪儿",
            "douyin": "抖音",
            "multi": "多渠道",
        }.get(platform, platform)
