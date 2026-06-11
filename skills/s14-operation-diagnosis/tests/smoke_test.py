#!/usr/bin/env python3
"""Smoke test for the standalone S14 OpenClaw skill package.

This test creates a temporary SQLite database, inserts one normalized S14
metrics row, calls the OpenClaw runtime entrypoint, and verifies the key output.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="s14_openclaw_") as tmp:
        tmp_dir = Path(tmp)
        db_path = tmp_dir / "s14_test.sqlite"
        output_dir = tmp_dir / "outputs"

        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            create table fact_daily_metrics (
              hotel_id text, platform text, data_date text, hotel_name text, channel_source text,
              revpar real, adr real, occupancy real, room_revenue real, sold_room_nights real,
              available_room_nights real, exposure real, views real, peer_rank real,
              booking_conversion_rate real, payment_conversion_rate real, lost_orders real,
              lost_amount real, promo_amount real, promo_cost real, promo_roi real, promo_detail_ready integer,
              rating_total real, bad_review_rate real, unreplied_reviews real, field_completeness real
            );
            create table fact_room_fee_daily (
              hotel_id text, platform text, data_date text, adr real, price_completeness real
            );
            create table fact_room_status_snapshot (
              hotel_id text, platform text, snapshot_date text, available_room_nights real,
              inventory_health_rate real, room_type_health_rate real
            );
            create table jd04_extensions (
              hotel_id text, platform text, data_date text, image_quality_rating text, video_status text,
              room_selling_point_status text, entry_tag_quality text, completed_actions text,
              pending_actions text, review_reason text
            );
            """
        )
        conn.execute(
            """
            insert into fact_daily_metrics (
              hotel_id, platform, data_date, hotel_name, channel_source,
              revpar, adr, occupancy, room_revenue, sold_room_nights, available_room_nights, exposure, views,
              peer_rank, booking_conversion_rate, payment_conversion_rate, lost_orders,
              lost_amount, promo_amount, promo_cost, promo_roi, promo_detail_ready, rating_total, bad_review_rate,
              unreplied_reviews, field_completeness
            ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "puyue",
                "fliggy",
                "2026-06-10",
                "贵阳璞悦·奢电竞酒店",
                "飞猪",
                160,
                140,
                0.82,
                42000,
                300,
                300,
                9000,
                1000,
                0.35,
                0.07,
                0.03,
                4,
                800,
                12000,
                2000,
                6,
                1,
                4.7,
                0.02,
                0,
                0.92,
            ),
        )
        conn.execute(
            "insert into fact_room_fee_daily values (?,?,?,?,?)",
            ("puyue", "fliggy", "2026-06-10", 140, 0.9),
        )
        conn.execute(
            "insert into fact_room_status_snapshot values (?,?,?,?,?,?)",
            ("puyue", "fliggy", "2026-06-10", 300, 0.85, 0.8),
        )
        conn.execute(
            "insert into jd04_extensions values (?,?,?,?,?,?,?,?,?,?)",
            (
                "puyue",
                "fliggy",
                "2026-06-10",
                "good",
                "complete",
                "partial",
                "complete",
                "已完成首图优化",
                "补充CPC数据",
                "转化补采",
            ),
        )
        conn.commit()
        conn.close()

        sys.path.insert(0, str(ROOT))
        from runtime import S14OperationDiagnosis

        result = S14OperationDiagnosis({"db_kind": "sqlite", "db_dsn": str(db_path)}).execute(
            {
                "hotel_id": "puyue",
                "platform": "fliggy",
                "period_start": "2026-06-01",
                "period_end": "2026-06-10",
                "output_dir": str(output_dir),
                "dry_run": True,
            }
        )

        assert result["status"] == "ok", result
        assert result["skill_id"] == "s14-operation-diagnosis", result
        assert len(result["module_scores"]) == 8, result
        assert [item["module_id"] for item in result["module_scores"]] == ["M01", "M02", "M03", "M04", "M05", "M06", "M07", "M08"], result
        assert round(sum(float(item["weight"]) for item in result["module_scores"]), 2) == 100, result
        assert result["formula_source"] == "runtime/calculator.py", result
        assert result["data_source"] == "hotel_pricing_tables", result
        assert len(result["execution_steps"]) == 8, result
        assert result["execution_steps"][1]["step"] == "S01B_VALIDATE_DATA_SOURCE", result
        assert result["execution_steps"][-1]["step"] == "S07_VALIDATE_OUTPUT", result
        assert "【S14 酒店 OTA 诊断报告已生成】" in result["feishu_message"], result
        assert "报告链接：" in result["feishu_message"], result
        assert "revpar" in result["calculated_fields"], result
        assert result["field_contract_file"] == "references/excel_field_mapping.xlsx", result
        assert any(item["field"] == "occupancy" and item["formula_module"] == "M01" for item in result["mapped_fields"]), result
        assert Path(result["report_file_path"]).exists(), result

        print("S14 smoke test passed")
        print(f"final_score={result['final_score']}")
        print(f"module_count={len(result['module_scores'])}")
        print(f"report_file_path={result['report_file_path']}")


if __name__ == "__main__":
    main()
