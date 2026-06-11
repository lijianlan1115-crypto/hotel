from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from runtime.common import DEFAULT_DB, DEFAULT_LOG_DIR, emit, json_dumps, now_local


def ensure_dirs(db_path: str = DEFAULT_DB) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(DEFAULT_LOG_DIR).mkdir(parents=True, exist_ok=True)


def connect(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    ensure_dirs(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(args: argparse.Namespace) -> None:
    with closing(connect(args.db)) as conn:
        with conn:
            conn.executescript(
                """
            CREATE TABLE IF NOT EXISTS hotels (
              hotel_id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              org_id TEXT,
              pms_vendor TEXT,
              timezone TEXT DEFAULT 'Asia/Shanghai',
              config_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS room_types (
              hotel_id TEXT NOT NULL,
              room_type_id TEXT NOT NULL,
              name TEXT NOT NULL,
              floor_price REAL,
              ceiling_price REAL,
              inventory INTEGER,
              config_json TEXT NOT NULL DEFAULT '{}',
              PRIMARY KEY (hotel_id, room_type_id)
            );
            CREATE TABLE IF NOT EXISTS snapshots (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              hotel_id TEXT NOT NULL,
              captured_at TEXT NOT NULL,
              source TEXT NOT NULL,
              payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS baselines (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              hotel_id TEXT NOT NULL,
              business_date TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              UNIQUE(hotel_id, business_date)
            );
            CREATE TABLE IF NOT EXISTS approvals (
              approval_id TEXT PRIMARY KEY,
              hotel_id TEXT NOT NULL,
              action_type TEXT NOT NULL,
              status TEXT NOT NULL,
              requested_by TEXT,
              approved_by TEXT,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS api_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              hotel_id TEXT,
              method TEXT NOT NULL,
              request_summary_json TEXT NOT NULL,
              response_summary_json TEXT,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS calendar_days (
              date TEXT PRIMARY KEY,
              year INTEGER NOT NULL,
              month INTEGER NOT NULL,
              day INTEGER NOT NULL,
              weekday INTEGER NOT NULL,
              is_weekend INTEGER NOT NULL,
              is_workday INTEGER NOT NULL,
              is_holiday INTEGER NOT NULL,
              is_adjusted_workday INTEGER NOT NULL,
              is_off_day INTEGER NOT NULL,
              holiday_name TEXT,
              holiday_group TEXT,
              days_to_holiday INTEGER,
              days_after_holiday INTEGER,
              season_tag TEXT NOT NULL,
              school_vacation_tag TEXT NOT NULL,
              local_event_count INTEGER NOT NULL DEFAULT 0,
              event_heat_level TEXT NOT NULL DEFAULT 'none',
              demand_level TEXT NOT NULL,
              price_advice TEXT NOT NULL,
              source_quality TEXT NOT NULL,
              source TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS event_candidates (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              hotel_id TEXT NOT NULL,
              date TEXT NOT NULL,
              event_name TEXT NOT NULL,
              event_type TEXT,
              location TEXT,
              distance_km REAL,
              source_url TEXT,
              confidence REAL NOT NULL DEFAULT 0,
              expected_heat TEXT NOT NULL DEFAULT 'unknown',
              status TEXT NOT NULL DEFAULT 'candidate',
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS command_menus (
              menu_id TEXT PRIMARY KEY,
              chat_id TEXT NOT NULL,
              starter_open_id TEXT NOT NULL,
              starter_role TEXT NOT NULL,
              hotel_id TEXT NOT NULL,
              status TEXT NOT NULL,
              selected_command_id TEXT,
              expires_at TEXT NOT NULL,
              payload_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_command_menus_chat_status
              ON command_menus(chat_id, status, expires_at);
            CREATE INDEX IF NOT EXISTS idx_command_menus_owner_status
              ON command_menus(chat_id, starter_open_id, status, expires_at);
            """
            )
    emit({"status": "ok", "db": args.db, "message": "hotel OTA runtime database initialized"})


def seed_demo(args: argparse.Namespace) -> None:
    ts = now_local()
    hotel = {
        "hotel_id": "puyue",
        "name": "璞悦·奢电竞酒店",
        "org_id": "",
        "pms_vendor": "Beyondh",
        "timezone": "Asia/Shanghai",
        "config_json": json_dumps(
            {
                "roles": {"owner": ["approve_execute"], "operator": ["diagnose"], "frontdesk": ["report"]},
                "channels": ["Mtop", "QZAgent", "meituan"],
                "pricing": {"single_change_limit_pct": 0.15, "default_requires_approval": True},
            }
        ),
    }
    rooms = [
        ("SINGLE", "独享电竞单人间", 122, 260, 4),
        ("KING", "至臻电竞大床房", 139, 300, 6),
        ("TWIN", "至臻电竞双床房", 139, 320, 6),
        ("DUO", "开黑电竞双床房", 152, 360, 5),
        ("QUAD", "竞技电竞四人间", 188, 520, 4),
        ("FIVE", "征途电竞五人套房", 220, 620, 2),
        ("MAHJONG", "汇赢麻将双床房", 139, 320, 2),
        ("FAMILY", "乐享亲子三人间", 139, 320, 1),
        ("BUNK", "舒享上下铺麻将房", 122, 280, 1),
    ]
    with closing(connect(args.db)) as conn:
        with conn:
            conn.execute(
                """
            INSERT INTO hotels (hotel_id, name, org_id, pms_vendor, timezone, config_json, created_at, updated_at)
            VALUES (:hotel_id, :name, :org_id, :pms_vendor, :timezone, :config_json, :created_at, :updated_at)
            ON CONFLICT(hotel_id) DO UPDATE SET
              name=excluded.name,
              org_id=excluded.org_id,
              pms_vendor=excluded.pms_vendor,
              timezone=excluded.timezone,
              config_json=excluded.config_json,
              updated_at=excluded.updated_at
            """,
                {**hotel, "created_at": ts, "updated_at": ts},
            )
            for room_type_id, name, floor, ceiling, inventory in rooms:
                conn.execute(
                    """
                INSERT INTO room_types (hotel_id, room_type_id, name, floor_price, ceiling_price, inventory, config_json)
                VALUES (?, ?, ?, ?, ?, ?, '{}')
                ON CONFLICT(hotel_id, room_type_id) DO UPDATE SET
                  name=excluded.name,
                  floor_price=excluded.floor_price,
                  ceiling_price=excluded.ceiling_price,
                  inventory=excluded.inventory
                """,
                    ("puyue", room_type_id, name, floor, ceiling, inventory),
                )
    emit({"status": "ok", "hotel_id": "puyue", "room_types": len(rooms)})


def log_api(
    hotel_id: str | None,
    method: str,
    request_summary: dict[str, Any],
    response_summary: dict[str, Any],
    status: str,
    db: str,
) -> None:
    with closing(connect(db)) as conn:
        with conn:
            conn.execute(
                """
            INSERT INTO api_logs (hotel_id, method, request_summary_json, response_summary_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    hotel_id,
                    method,
                    json_dumps(request_summary),
                    json_dumps(response_summary),
                    status,
                    now_local(),
                ),
            )


def approval_create(args: argparse.Namespace) -> None:
    payload = json.loads(args.payload)
    from runtime.safety.approvals import validate_approval_payload

    payload_gate = validate_approval_payload(payload, args.action_type)
    if not payload_gate["allowed"]:
        emit(
            {
                "status": "blocked",
                "reason": payload_gate["reason"],
                "approval_required": False,
                "template_id": payload_gate.get("template_id"),
                "payload_gate": payload_gate,
            }
        )
        return
    approval_id = f"appr-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    ts = now_local()
    with closing(connect(args.db)) as conn:
        with conn:
            conn.execute(
                """
            INSERT INTO approvals (approval_id, hotel_id, action_type, status, requested_by, approved_by, payload_json, created_at, updated_at)
            VALUES (?, ?, ?, 'pending', ?, NULL, ?, ?, ?)
            """,
                (approval_id, args.hotel_id, args.action_type, args.requested_by, json_dumps(payload), ts, ts),
            )
    emit(
        {
            "status": "ok",
            "approval_id": approval_id,
            "approval_status": "pending",
            "data_business_date": payload.get("data_business_date"),
            "data_snapshot_time": payload.get("data_snapshot_time"),
            "freshness_status": payload.get("freshness_status"),
            "dry_run_summary": payload.get("dry_run_summary"),
        }
    )


def approval_get(db_path: str, approval_id: str | None) -> dict[str, Any] | None:
    if not approval_id:
        return None
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT approval_id, hotel_id, action_type, status, requested_by, approved_by, payload_json, created_at, updated_at
            FROM approvals WHERE approval_id=?
            """,
            (approval_id,),
        ).fetchone()
    if row is None:
        return None
    record = dict(row)
    try:
        record["payload"] = json.loads(record.pop("payload_json"))
    except json.JSONDecodeError:
        record["payload"] = {}
    return record


def approval_mark(args: argparse.Namespace) -> None:
    status = "approved" if args.approve else "rejected"
    with closing(connect(args.db)) as conn:
        with conn:
            cur = conn.execute(
                "UPDATE approvals SET status=?, approved_by=?, updated_at=? WHERE approval_id=?",
                (status, args.user, now_local(), args.approval_id),
            )
    emit({"status": "ok" if cur.rowcount else "not_found", "approval_id": args.approval_id, "approval_status": status})
