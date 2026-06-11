from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
from urllib.parse import parse_qs, unquote, urlparse
from typing import Any

from runtime.common import DEFAULT_DB, emit, now_local, redacted_request
from runtime.contracts import validate_contract


DB_KINDS = ("sqlite", "mysql", "postgres")
TEMPLATES = (
    "operating_snapshot",
    "price_snapshot",
    "order_snapshot",
    "demand_context",
    "operation_diagnosis",
    "sales_baseline",
    "daily_metrics",
    "monthly_metrics",
    "reservation_snapshot",
    "stayover_snapshot",
)
INSPECT_MODES = ("connection", "tables", "columns", "sample")
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")
SENSITIVE_FIELD_PATTERNS = ("password", "token", "secret", "mobile", "phone", "id_card", "guest_name", "room_no", "order_no", "operator_name")
DAILY_PERIOD_TYPE_ALIASES = ("本日", "今日", "当天", "当日", "日", "day", "daily", "today", "current_day")


SQLITE_TEMPLATES = {
    "operating_snapshot": """
        SELECT
          h.hotel_id,
          h.name AS hotel_name,
          COUNT(rt.room_type_id) AS room_type_count,
          COALESCE(SUM(rt.inventory), 0) AS available_rooms,
          COALESCE(AVG(rt.floor_price), 0) AS avg_floor_price,
          COALESCE(AVG(rt.ceiling_price), 0) AS avg_ceiling_price
        FROM hotels h
        LEFT JOIN room_types rt ON rt.hotel_id = h.hotel_id
        WHERE h.hotel_id = ?
        GROUP BY h.hotel_id, h.name
    """,
    "price_snapshot": """
        SELECT
          room_type_id,
          name AS room_type_name,
          floor_price,
          ceiling_price,
          inventory
        FROM room_types
        WHERE hotel_id = ?
        ORDER BY room_type_id
    """,
    "order_snapshot": """
        SELECT
          hotel_id,
          captured_at,
          payload_json
        FROM snapshots
        WHERE hotel_id = ?
        ORDER BY captured_at DESC, id DESC
        LIMIT 5
    """,
}


def _source(db_kind: str, field_quality: str = "confirmed") -> dict[str, Any]:
    return {
        "adapter_vendor": "database",
        "channel_source": "pms",
        "data_source_type": f"{db_kind}_db",
        "source_capability": "read_only",
        "field_quality": field_quality,
        "captured_at": now_local(),
    }


def _parse_data_datetime(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min)
    text = str(value).strip()
    if not text:
        return None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            parsed = dt.datetime.fromisoformat(candidate)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            pass
    return None


def freshness_metadata(value: Any, *, demo_data: bool = False) -> dict[str, Any]:
    if demo_data:
        return {
            "freshness_status": "demo_data",
            "data_age_hours": None,
            "data_business_date": None,
            "data_snapshot_time": None,
            "business_status": "demo_or_historical",
            "today_label_allowed": False,
        }
    parsed = _parse_data_datetime(value)
    if parsed is None:
        return {
            "freshness_status": "missing_date",
            "data_age_hours": None,
            "data_business_date": None,
            "data_snapshot_time": None,
            "business_status": "demo_or_historical",
            "today_label_allowed": False,
        }
    now = dt.datetime.now()
    age_hours = max(0.0, (now - parsed).total_seconds() / 3600)
    status = "fresh" if parsed.date() == now.date() and age_hours <= 24 else "stale"
    today_label_allowed = status == "fresh" and age_hours <= 72
    return {
        "freshness_status": status,
        "data_age_hours": round(age_hours, 2),
        "data_business_date": parsed.date().isoformat(),
        "data_snapshot_time": parsed.strftime("%Y-%m-%d %H:%M:%S"),
        "business_status": "current" if status == "fresh" else "demo_or_historical",
        "today_label_allowed": today_label_allowed,
    }


def _append_freshness_risk(payload: dict[str, Any]) -> None:
    status = payload.get("freshness_status")
    if status not in ("stale", "missing_date", "demo_data"):
        return
    risks = payload.setdefault("risk_flags", [])
    risk = f"data_freshness_{status}"
    if risk not in risks:
        risks.append(risk)
    if (payload.get("data_age_hours") or 0) > 72 and "data_stale_over_72h" not in risks:
        risks.append("data_stale_over_72h")


def _connect_sqlite(dsn: str | None) -> sqlite3.Connection:
    path = dsn or os.environ.get("HOTEL_OTA_DB_DSN") or os.environ.get("HOTEL_OTA_DB") or DEFAULT_DB
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _mask(value: Any) -> Any:
    if value in (None, ""):
        return value
    text = str(value)
    if len(text) <= 2:
        return "***"
    if len(text) <= 6:
        return text[:1] + "***"
    return text[:2] + "***" + text[-2:]


def _redact_row(row: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in row.items():
        lowered = key.lower()
        if any(pattern in lowered for pattern in SENSITIVE_FIELD_PATTERNS):
            redacted[key] = _mask(value)
        else:
            redacted[key] = value
    return redacted


def _safe_identifier(name: str, label: str = "identifier") -> str:
    if not name or not SAFE_IDENTIFIER.match(name):
        raise ValueError(f"unsafe {label}: {name}")
    return f"`{name}`"


def _missing_driver(db_kind: str) -> dict[str, Any]:
    driver = "pymysql" if db_kind == "mysql" else "psycopg"
    try:
        __import__(driver)
    except ImportError:
        return {
            "status": "blocked",
            "reason": "missing_driver",
            "db_kind": db_kind,
            "required_driver": driver,
            "message": f"Install {driver} and configure HOTEL_OTA_DB_DSN before using {db_kind}.",
        }
    return {}


def _load_mapping_config(path: str | None = None) -> dict[str, Any] | None:
    config_path = path or os.environ.get("HOTEL_OTA_DB_MAPPING_CONFIG")
    if not config_path:
        return None
    with open(config_path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _profile(config: dict[str, Any] | None, profile_name: str | None = None) -> dict[str, Any] | None:
    if not config:
        return None
    profiles = config.get("profiles") or {}
    selected = profile_name or os.environ.get("HOTEL_OTA_DB_PROFILE") or config.get("default_profile")
    if not selected:
        return None
    profile = profiles.get(selected)
    if profile:
        parent_name = profile.get("inherits")
        if parent_name and parent_name in profiles:
            parent = json.loads(json.dumps(profiles[parent_name]))
            parent.update(profile)
            for key in ("tables", "columns", "metric_aliases", "status_aliases", "hotel_ids", "privacy"):
                if isinstance(profiles[parent_name].get(key), dict):
                    merged = dict(profiles[parent_name][key])
                    merged.update(profile.get(key) or {})
                    parent[key] = merged
            profile = parent
        else:
            profile = dict(profile)
        profile["_profile_name"] = selected
    return profile


def _dsn_from_args(args: argparse.Namespace, profile: dict[str, Any] | None = None) -> str:
    dsn_env = (profile or {}).get("dsn_env")
    return (
        getattr(args, "dsn", None)
        or (os.environ.get(dsn_env) if dsn_env else None)
        or os.environ.get("HOTEL_OTA_DB_DSN")
        or (profile or {}).get("dsn")
        or ""
    )


def _parse_mysql_dsn(dsn: str) -> dict[str, Any]:
    if not dsn:
        raise ValueError("HOTEL_OTA_DB_DSN is required for mysql")
    parsed = urlparse(dsn)
    if parsed.scheme not in ("mysql", "mysql+pymysql"):
        raise ValueError("mysql DSN must start with mysql://")
    query = parse_qs(parsed.query)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": (parsed.path or "/").lstrip("/"),
        "charset": query.get("charset", ["utf8mb4"])[0],
        "connect_timeout": int(query.get("connect_timeout", ["10"])[0]),
    }


def _connect_mysql(args: argparse.Namespace, profile: dict[str, Any] | None = None):
    missing = _missing_driver("mysql")
    if missing:
        return None, missing
    import pymysql

    params = _parse_mysql_dsn(_dsn_from_args(args, profile))
    conn = pymysql.connect(
        host=params["host"],
        port=params["port"],
        user=params["user"],
        password=params["password"],
        database=params["database"],
        charset=params["charset"],
        connect_timeout=params["connect_timeout"],
        read_timeout=20,
        write_timeout=20,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )
    return conn, {}


def _table(profile: dict[str, Any], key: str) -> str:
    tables = profile.get("tables") or {}
    table = tables.get(key)
    if not table:
        raise KeyError(f"database table mapping required: {key}")
    return table


def _columns(profile: dict[str, Any], key: str) -> dict[str, str]:
    columns = (profile.get("columns") or {}).get(key) or {}
    if not columns:
        raise KeyError(f"database column mapping required: {key}")
    return columns


def _col(columns: dict[str, str], key: str) -> str:
    value = columns.get(key)
    if not value:
        raise KeyError(f"database column mapping required: {key}")
    return value


def _hotel_name(profile: dict[str, Any], hotel_id: str) -> str:
    hotels = profile.get("hotel_ids") or {}
    hotel = hotels.get(hotel_id)
    if isinstance(hotel, dict):
        return hotel.get("hotel_name") or hotel.get("name") or hotel_id
    if isinstance(hotel, str):
        return hotel
    return hotel_id


def _normalize_metric_name(metric_name: str, aliases: dict[str, list[str]]) -> str:
    normalized = str(metric_name).strip()
    for key, names in aliases.items():
        if normalized == key or normalized in names:
            return key
    return normalized


def _normalize_status(status: str, aliases: dict[str, list[str]]) -> str:
    normalized = str(status).strip()
    for key, names in aliases.items():
        if normalized == key or normalized in names:
            return key
    return "other"


def _latest_date_condition(table: str, hotel_col: str, date_col: str) -> str:
    safe_table = _safe_identifier(table, "table")
    safe_hotel = _safe_identifier(hotel_col, "column")
    safe_date = _safe_identifier(date_col, "column")
    return f"{safe_date} = (SELECT MAX({safe_date}) FROM {safe_table} WHERE {safe_hotel} = %s)"


def _target_date(args: argparse.Namespace) -> str:
    value = getattr(args, "date", None)
    if value:
        return str(value)[:10]
    return dt.datetime.now().date().isoformat()


def _first_existing(columns: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        if key in columns and columns[key]:
            return columns[key]
    return None


def _has_template_mapping(profile: dict[str, Any], key: str) -> bool:
    return bool((profile.get("tables") or {}).get(key) and (profile.get("columns") or {}).get(key))


def _date_filter_clause(args: argparse.Namespace, table: str, hotel_col: str, date_col: str, hotel_name: str) -> tuple[str, list[Any]]:
    if getattr(args, "date", None):
        return f"DATE({_safe_identifier(date_col, 'column')}) = %s", [_target_date(args)]
    return _latest_date_condition(table, hotel_col, date_col), [hotel_name]


def _to_float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int_or_none(value: Any) -> int | None:
    number = _to_float_or_none(value)
    if number is None:
        return None
    return int(round(number))


def _parse_structured_value(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _parse_field_pairs(value: Any) -> dict[str, Any]:
    parsed = _parse_structured_value(value)
    if isinstance(parsed, dict):
        return parsed
    if not isinstance(parsed, str):
        return {}
    result: dict[str, Any] = {}
    for part in re.split(r"[;,\n]+", parsed):
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        key = key.strip()
        raw = raw.strip()
        if not key:
            continue
        number = _to_float_or_none(raw)
        result[key] = number if number is not None else raw
    return result


def _normalize_hourly_curve(value: Any, target_orders: int | None = None) -> list[dict[str, int]]:
    parsed = _parse_structured_value(value)
    rows: list[dict[str, int]] = []
    if isinstance(parsed, dict):
        items = parsed.items()
        for hour, target in items:
            if isinstance(target, dict):
                target = target.get("target_orders") or target.get("target")
            hour_int = _to_int_or_none(hour)
            target_int = _to_int_or_none(target)
            if hour_int is not None and target_int is not None:
                rows.append({"hour": hour_int, "target_orders": target_int})
    elif isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                hour_int = _to_int_or_none(item.get("hour"))
                target_int = _to_int_or_none(item.get("target_orders") or item.get("target"))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                hour_int = _to_int_or_none(item[0])
                target_int = _to_int_or_none(item[1])
            else:
                continue
            if hour_int is not None and target_int is not None:
                rows.append({"hour": hour_int, "target_orders": target_int})
    rows = sorted(rows, key=lambda item: item["hour"])
    if rows:
        return rows
    if target_orders is None:
        return []
    anchors = [(12, 0.34), (16, 0.62), (20, 0.86)]
    return [{"hour": hour, "target_orders": max(1, int(round(target_orders * ratio)))} for hour, ratio in anchors]


def _progress_checkpoints_from_curve(curve: list[dict[str, int]], target_orders: int) -> list[dict[str, int | str]]:
    names = {12: "midday", 16: "afternoon", 20: "evening_peak"}
    result = []
    for hour in (12, 16, 20):
        match = next((item for item in curve if int(item.get("hour", -1)) == hour), None)
        if match:
            target = int(match.get("target_orders") or 0)
        else:
            ratio = {12: 0.34, 16: 0.62, 20: 0.86}[hour]
            target = int(round(target_orders * ratio))
        result.append({"hour": hour, "checkpoint": names[hour], "target_orders": max(target, 1)})
    return result


def _sqlite_operating_snapshot(row: sqlite3.Row | None, hotel_id: str) -> dict[str, Any]:
    if row is None:
        payload = {"hotel_id": hotel_id, "available_rooms": 0, "sold_rooms": 0, "remaining_rooms": 0, "risk_flags": ["database_no_hotel_row"], **freshness_metadata(None)}
        _append_freshness_risk(payload)
        return payload
    available = int(row["available_rooms"] or 0)
    payload = {
        "hotel_id": row["hotel_id"],
        "hotel_name": row["hotel_name"],
        "room_type_count": int(row["room_type_count"] or 0),
        "available_rooms": available,
        "sold_rooms": 0,
        "remaining_rooms": available,
        "occupancy_rate": 0,
        "adr": round(float(row["avg_floor_price"] or 0), 2),
        "revpar": 0,
        "risk_flags": ["database_read_only_snapshot"],
        **freshness_metadata(None),
    }
    _append_freshness_risk(payload)
    return payload


def _sqlite_price_snapshot(rows: list[sqlite3.Row]) -> dict[str, Any]:
    prices = []
    for row in rows:
        prices.append(
            {
                "room_type_id": row["room_type_id"],
                "room_type_name": row["room_type_name"],
                "current_price": row["floor_price"],
                "listed_price": row["ceiling_price"],
                "price_floor": row["floor_price"],
                "price_ceiling": row["ceiling_price"],
                "available_rooms": row["inventory"],
            }
        )
    return {"price_snapshots": prices}


def _sqlite_order_snapshot(rows: list[sqlite3.Row]) -> dict[str, Any]:
    orders = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            payload = {"raw": row["payload_json"]}
        orders.append(
            {
                "hotel_id": row["hotel_id"],
                "captured_at": row["captured_at"],
                "order_status": "snapshot_reference",
                "order_status_raw": "snapshot_payload",
                "price_detail": payload,
            }
        )
    return {"orders": orders}


def _query_sqlite(args: argparse.Namespace) -> dict[str, Any]:
    with _connect_sqlite(args.dsn) as conn:
        sql = SQLITE_TEMPLATES[args.template]
        if args.template == "operating_snapshot":
            row = conn.execute(sql, (args.hotel_id,)).fetchone()
            payload = _sqlite_operating_snapshot(row, args.hotel_id)
        elif args.template == "price_snapshot":
            rows = conn.execute(sql, (args.hotel_id,)).fetchall()
            payload = _sqlite_price_snapshot(rows)
        elif args.template == "order_snapshot":
            rows = conn.execute(sql, (args.hotel_id,)).fetchall()
            payload = _sqlite_order_snapshot(rows)
        else:
            raise ValueError(f"unsupported template: {args.template}")
    return {**_source("sqlite"), "template": args.template, "hotel_id": args.hotel_id, "payload": payload}


def _mysql_latest_metrics(conn, profile: dict[str, Any], hotel_name: str, monthly: bool = False, date: str | None = None) -> dict[str, Any]:
    table_key = "monthly_metrics" if monthly else "daily_metrics"
    date_key = "period_month" if monthly else "business_date"
    table = _table(profile, table_key)
    columns = _columns(profile, table_key)
    hotel_col = _col(columns, "hotel_name")
    date_col = _col(columns, date_key)
    aliases = profile.get("metric_aliases") or {}
    safe_table = _safe_identifier(table, "table")
    select_cols = {
        "metric_group": _col(columns, "metric_group"),
        "metric_item": _col(columns, "metric_item"),
        "metric_name": _col(columns, "metric_name"),
        "metric_value": _col(columns, "metric_value"),
        date_key: date_col,
    }
    optional = "compare_type" if monthly else "period_type"
    if optional in columns:
        select_cols[optional] = columns[optional]
    projection = ", ".join(f"{_safe_identifier(col, 'column')} AS `{alias}`" for alias, col in select_cols.items())
    safe_hotel_col = _safe_identifier(hotel_col, "column")
    safe_date_col = _safe_identifier(date_col, "column")
    where_parts = [f"{safe_hotel_col} = %s"]
    where_params: list[Any] = [hotel_name]
    latest_parts = [f"{safe_hotel_col} = %s"]
    latest_params: list[Any] = [hotel_name]
    if not monthly and "period_type" in columns:
        period_col = _safe_identifier(columns["period_type"], "column")
        period_aliases = tuple(str(item) for item in (profile.get("daily_period_type_aliases") or DAILY_PERIOD_TYPE_ALIASES))
        placeholders = ", ".join(["%s"] * len(period_aliases))
        where_parts.append(f"TRIM({period_col}) IN ({placeholders})")
        where_params.extend(period_aliases)
        latest_parts.append(f"TRIM({period_col}) IN ({placeholders})")
        latest_params.extend(period_aliases)
    if date:
        where_latest = f"DATE({safe_date_col}) = %s" if not monthly else f"{safe_date_col} = %s"
        where_params.append(str(date)[:7] if monthly else str(date)[:10])
        latest_params = []
    else:
        where_latest = f"{safe_date_col} = (SELECT MAX({safe_date_col}) FROM {safe_table} WHERE {' AND '.join(latest_parts)})"
    sql = f"SELECT {projection} FROM {safe_table} WHERE {' AND '.join(where_parts)} AND {where_latest}"
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple(where_params + latest_params))
        rows = cursor.fetchall()
    metrics = []
    normalized: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    data_date = None
    for row in rows:
        item = dict(row)
        data_date = data_date or item.get(date_key)
        name = str(item.get("metric_name") or "")
        unified = _normalize_metric_name(name, aliases)
        item["metric_key"] = unified
        metrics.append(item)
        if unified in normalized:
            existing = normalized.get(unified)
            incoming = item.get("metric_value")
            if str(existing) != str(incoming):
                conflicts.append({"metric_key": unified, "kept_value": existing, "ignored_value": incoming})
            continue
        normalized[unified] = item.get("metric_value")
    result = {"metrics": metrics, "normalized_metrics": normalized, "metric_resolution_policy": "first_metric_value_wins"}
    if conflicts:
        result["metric_conflict_warning"] = conflicts
        result["risk_flags"] = ["metric_conflict_warning"]
    if monthly:
        result["data_period_month"] = str(data_date) if data_date is not None else None
    else:
        result["data_business_date"] = str(data_date) if data_date is not None else None
    return result


def _query_mysql_business_operating_snapshot(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    hotel_name = _hotel_name(profile, args.hotel_id)
    table = _table(profile, "operating_snapshot")
    columns = _columns(profile, "operating_snapshot")
    hotel_col = _col(columns, "hotel_name")
    date_col = _col(columns, "business_date")
    wanted = [
        "hotel_name",
        "business_date",
        "occupancy_rate",
        "adr",
        "revpar",
        "available_rooms",
        "sold_rooms",
        "remaining_rooms",
        "orders_today",
        "risk_flags",
    ]
    projection = [f"{_safe_identifier(columns[key], 'column')} AS `{key}`" for key in wanted if key in columns]
    safe_table = _safe_identifier(table, "table")
    date_clause, date_params = _date_filter_clause(args, table, hotel_col, date_col, hotel_name)
    sql = (
        f"SELECT {', '.join(projection)} FROM {safe_table} "
        f"WHERE {_safe_identifier(hotel_col, 'column')} = %s AND {date_clause} "
        f"ORDER BY {_safe_identifier(date_col, 'column')} DESC LIMIT 1"
    )
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple([hotel_name] + date_params))
        row = cursor.fetchone()
    if not row:
        payload = {"hotel_id": args.hotel_id, "hotel_name": hotel_name, "risk_flags": ["business_dataset_no_operating_snapshot_row"], **freshness_metadata(None)}
        _append_freshness_risk(payload)
        return payload
    data_date = row.get("business_date")
    sold_rooms = _to_int_or_none(row.get("sold_rooms")) or 0
    remaining_rooms = _to_int_or_none(row.get("remaining_rooms"))
    available_rooms = _to_int_or_none(row.get("available_rooms"))
    total_rooms = (sold_rooms + remaining_rooms) if remaining_rooms is not None else (sold_rooms + (available_rooms or 0))
    risk_flags = _parse_structured_value(row.get("risk_flags"))
    if isinstance(risk_flags, str):
        risk_flags = [item.strip() for item in re.split(r"[,;]", risk_flags) if item.strip()]
    if not isinstance(risk_flags, list):
        risk_flags = []
    payload = {
        "hotel_id": args.hotel_id,
        "hotel_name": row.get("hotel_name") or hotel_name,
        "total_rooms": total_rooms,
        "available_rooms": available_rooms,
        "sold_rooms": sold_rooms,
        "occupied_rooms": sold_rooms,
        "remaining_rooms": remaining_rooms,
        "orders_today": _to_int_or_none(row.get("orders_today")),
        "occupancy_rate": _to_float_or_none(row.get("occupancy_rate")) or 0,
        "adr": _to_float_or_none(row.get("adr")) or 0,
        "revpar": _to_float_or_none(row.get("revpar")) or 0,
        "risk_flags": ["business_dataset_v1_operating_snapshot"] + risk_flags,
        "source_table": table,
        **freshness_metadata(data_date),
    }
    _append_freshness_risk(payload)
    return payload


def _query_mysql_business_price_snapshot(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    hotel_name = _hotel_name(profile, args.hotel_id)
    table = _table(profile, "price_data")
    columns = _columns(profile, "price_data")
    hotel_col = _col(columns, "hotel_name")
    date_col = _col(columns, "business_date")
    wanted = [
        "hotel_name",
        "business_date",
        "room_type_id",
        "room_type_name",
        "channel",
        "current_price",
        "price_floor",
        "price_ceiling",
        "normal_price",
        "weekend_price",
        "begin_date",
        "end_date",
        "competitor_price",
    ]
    projection = [f"{_safe_identifier(columns[key], 'column')} AS `{key}`" for key in wanted if key in columns]
    safe_table = _safe_identifier(table, "table")
    date_clause, date_params = _date_filter_clause(args, table, hotel_col, date_col, hotel_name)
    sql = (
        f"SELECT {', '.join(projection)} FROM {safe_table} "
        f"WHERE {_safe_identifier(hotel_col, 'column')} = %s AND {date_clause} "
        f"ORDER BY {_safe_identifier(date_col, 'column')} DESC"
    )
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple([hotel_name] + date_params))
        rows = cursor.fetchall()
    prices = []
    latest_business_date = None
    for row in rows:
        room_type = str(row.get("room_type_id") or "unknown")
        room_type_name = row.get("room_type_name") or room_type
        latest_business_date = latest_business_date or row.get("business_date")
        prices.append(
            {
                "room_type_id": room_type,
                "room_type_name": room_type_name,
                "channel": row.get("channel"),
                "current_price": row.get("current_price"),
                "listed_price": row.get("normal_price") or row.get("current_price"),
                "price_floor": row.get("price_floor"),
                "price_ceiling": row.get("price_ceiling"),
                "normal_price": row.get("normal_price"),
                "weekend_price": row.get("weekend_price"),
                "begin_date": str(row.get("begin_date"))[:10] if row.get("begin_date") is not None else None,
                "end_date": str(row.get("end_date"))[:10] if row.get("end_date") is not None else None,
                "competitor_price": row.get("competitor_price"),
                "business_date": str(row.get("business_date"))[:10] if row.get("business_date") is not None else None,
                "price_guard_source": "price_data",
            }
        )
    payload = {
        "price_snapshots": prices,
        "price_snapshot_source": "business_dataset_v1.price_data",
        "risk_flags": ["business_dataset_v1_price_data", "current_price_may_be_rs01_actual_average_not_realtime_ota_listing"],
        **freshness_metadata(latest_business_date),
    }
    _append_freshness_risk(payload)
    return payload


def _query_mysql_demand_context(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    hotel_name = _hotel_name(profile, args.hotel_id)
    table = _table(profile, "demand_context")
    columns = _columns(profile, "demand_context")
    hotel_col = _col(columns, "hotel_name")
    date_col = _col(columns, "business_date")
    wanted = [
        "hotel_name",
        "business_date",
        "calendar_context",
        "weather_context",
        "event_context",
        "competitor_context",
        "operating_context",
        "progress_context",
        "demand_signal",
    ]
    projection = [f"{_safe_identifier(columns[key], 'column')} AS `{key}`" for key in wanted if key in columns]
    safe_table = _safe_identifier(table, "table")
    date_clause, date_params = _date_filter_clause(args, table, hotel_col, date_col, hotel_name)
    sql = (
        f"SELECT {', '.join(projection)} FROM {safe_table} "
        f"WHERE {_safe_identifier(hotel_col, 'column')} = %s AND {date_clause} "
        f"ORDER BY {_safe_identifier(date_col, 'column')} DESC LIMIT 1"
    )
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple([hotel_name] + date_params))
        row = cursor.fetchone()
    if not row:
        payload = {"hotel_id": args.hotel_id, "hotel_name": hotel_name, "risk_flags": ["business_dataset_no_demand_context_row"], **freshness_metadata(None)}
        _append_freshness_risk(payload)
        return payload
    demand_signal = _parse_field_pairs(row.get("demand_signal"))
    payload = {
        "hotel_id": args.hotel_id,
        "hotel_name": row.get("hotel_name") or hotel_name,
        "calendar_context": _parse_field_pairs(row.get("calendar_context")),
        "weather_context": _parse_field_pairs(row.get("weather_context")),
        "event_context": _parse_field_pairs(row.get("event_context")),
        "competitor_context": _parse_field_pairs(row.get("competitor_context")),
        "operating_context": _parse_field_pairs(row.get("operating_context")),
        "progress_context": _parse_field_pairs(row.get("progress_context")),
        "demand_signal": demand_signal or _parse_structured_value(row.get("demand_signal")),
        "demand_index": demand_signal.get("demand_index"),
        "demand_level": demand_signal.get("demand_level"),
        "risk_flags": ["business_dataset_v1_demand_context"],
        "source_table": table,
        **freshness_metadata(row.get("business_date")),
    }
    _append_freshness_risk(payload)
    return payload


def _query_mysql_operation_diagnosis(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    hotel_name = _hotel_name(profile, args.hotel_id)
    table = _table(profile, "operation_diagnosis")
    columns = _columns(profile, "operation_diagnosis")
    hotel_col = _col(columns, "hotel_name")
    date_col = _col(columns, "business_date")
    wanted = [
        "hotel_name",
        "business_date",
        "hos_score",
        "merchant_operation_score",
        "peer_rank",
        "exposure",
        "views",
        "payment_conversion_rate",
        "rating_total",
        "bad_review_rate",
        "ota_health_score",
    ]
    projection = [f"{_safe_identifier(columns[key], 'column')} AS `{key}`" for key in wanted if key in columns]
    safe_table = _safe_identifier(table, "table")
    date_clause, date_params = _date_filter_clause(args, table, hotel_col, date_col, hotel_name)
    sql = (
        f"SELECT {', '.join(projection)} FROM {safe_table} "
        f"WHERE {_safe_identifier(hotel_col, 'column')} = %s AND {date_clause} "
        f"ORDER BY {_safe_identifier(date_col, 'column')} DESC LIMIT 1"
    )
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple([hotel_name] + date_params))
        row = cursor.fetchone()
    if not row:
        payload = {"hotel_id": args.hotel_id, "hotel_name": hotel_name, "risk_flags": ["business_dataset_no_operation_diagnosis_row"], **freshness_metadata(None)}
        _append_freshness_risk(payload)
        return payload
    payload = {
        "hotel_id": args.hotel_id,
        "hotel_name": row.get("hotel_name") or hotel_name,
        "hos_score": _to_float_or_none(row.get("hos_score")),
        "merchant_operation_score": _to_float_or_none(row.get("merchant_operation_score")),
        "peer_rank": _to_int_or_none(row.get("peer_rank")),
        "exposure": _to_int_or_none(row.get("exposure")),
        "views": _to_int_or_none(row.get("views")),
        "payment_conversion_rate": _to_float_or_none(row.get("payment_conversion_rate")),
        "rating_total": _to_float_or_none(row.get("rating_total")),
        "bad_review_rate": _to_float_or_none(row.get("bad_review_rate")),
        "ota_health_score": _to_float_or_none(row.get("ota_health_score")),
        "risk_flags": ["business_dataset_v1_operation_diagnosis"],
        "source_table": table,
        **freshness_metadata(row.get("business_date")),
    }
    _append_freshness_risk(payload)
    return payload


def _query_mysql_sales_baseline(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    hotel_name = _hotel_name(profile, args.hotel_id)
    table = _table(profile, "sales_baseline")
    columns = _columns(profile, "sales_baseline")
    hotel_col = _col(columns, "hotel_name")
    date_col = _col(columns, "business_date")
    wanted = [
        "hotel_name",
        "business_date",
        "target_orders",
        "hourly_curve",
        "historical_same_weekday",
        "historical_same_date_type",
        "holiday_history",
        "completion_rate",
    ]
    projection = [f"{_safe_identifier(columns[key], 'column')} AS `{key}`" for key in wanted if key in columns]
    safe_table = _safe_identifier(table, "table")
    date_clause, date_params = _date_filter_clause(args, table, hotel_col, date_col, hotel_name)
    sql = (
        f"SELECT {', '.join(projection)} FROM {safe_table} "
        f"WHERE {_safe_identifier(hotel_col, 'column')} = %s AND {date_clause} "
        f"ORDER BY {_safe_identifier(date_col, 'column')} DESC LIMIT 1"
    )
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple([hotel_name] + date_params))
        row = cursor.fetchone()
    if not row:
        payload = {"hotel_id": args.hotel_id, "hotel_name": hotel_name, "risk_flags": ["business_dataset_no_sales_baseline_row"], **freshness_metadata(None)}
        _append_freshness_risk(payload)
        return payload
    target_orders = max(_to_int_or_none(row.get("target_orders")) or 0, 1)
    hourly_curve = _normalize_hourly_curve(row.get("hourly_curve"), target_orders)
    payload = {
        "hotel_id": args.hotel_id,
        "hotel_name": row.get("hotel_name") or hotel_name,
        "target_orders": target_orders,
        "hourly_curve": hourly_curve,
        "progress_checkpoints": _progress_checkpoints_from_curve(hourly_curve, target_orders),
        "historical_same_weekday": _parse_structured_value(row.get("historical_same_weekday")),
        "historical_same_date_type": _parse_structured_value(row.get("historical_same_date_type")),
        "holiday_history": _parse_structured_value(row.get("holiday_history")),
        "completion_rate": _to_float_or_none(row.get("completion_rate")),
        "risk_flags": ["business_dataset_v1_sales_baseline"],
        "source_table": table,
        **freshness_metadata(row.get("business_date")),
    }
    _append_freshness_risk(payload)
    return payload


def _query_mysql_operating_snapshot(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    if _has_template_mapping(profile, "operating_snapshot"):
        return _query_mysql_business_operating_snapshot(conn, args, profile)
    hotel_name = _hotel_name(profile, args.hotel_id)
    table = _table(profile, "room_status_snapshot")
    columns = _columns(profile, "room_status_snapshot")
    hotel_col = _col(columns, "hotel_name")
    time_col = _col(columns, "snapshot_time")
    status_col = _col(columns, "room_status")
    room_col = _col(columns, "room_no")
    safe_table = _safe_identifier(table, "table")
    latest = _latest_date_condition(table, hotel_col, time_col)
    sql = (
        f"SELECT {_safe_identifier(status_col, 'column')} AS room_status, "
        f"COUNT(DISTINCT {_safe_identifier(room_col, 'column')}) AS room_count, "
        f"MAX({_safe_identifier(time_col, 'column')}) AS snapshot_time "
        f"FROM {safe_table} WHERE {_safe_identifier(hotel_col, 'column')} = %s AND {latest} "
        f"GROUP BY {_safe_identifier(status_col, 'column')}"
    )
    with conn.cursor() as cursor:
        cursor.execute(sql, (hotel_name, hotel_name))
        rows = cursor.fetchall()
    aliases = profile.get("status_aliases") or {}
    category_counts = {"available_rooms": 0, "occupied_rooms": 0, "maintenance_rooms": 0, "dirty_rooms": 0, "other_rooms": 0}
    raw_status_counts = []
    snapshot_time = None
    for row in rows:
        raw = str(row.get("room_status") or "")
        count = int(row.get("room_count") or 0)
        category = _normalize_status(raw, aliases)
        if category.startswith("available"):
            category_counts["available_rooms"] += count
        elif category.startswith("occupied"):
            category_counts["occupied_rooms"] += count
        elif category == "maintenance":
            category_counts["maintenance_rooms"] += count
        elif "dirty" in category:
            category_counts["dirty_rooms"] += count
        else:
            category_counts["other_rooms"] += count
        raw_status_counts.append({"room_status": raw, "normalized_status": category, "room_count": count})
        snapshot_time = snapshot_time or row.get("snapshot_time")
    total_rooms = sum(category_counts.values())
    daily = {}
    daily_result = {}
    try:
        daily_result = _mysql_latest_metrics(conn, profile, hotel_name, monthly=False)
        daily = daily_result.get("normalized_metrics", {})
    except (KeyError, ValueError):
        daily = {}
    occupancy_rate = daily.get("occupancy_rate")
    if occupancy_rate is None and total_rooms:
        occupancy_rate = round(category_counts["occupied_rooms"] / total_rooms, 4)
    data_time = snapshot_time or daily_result.get("data_business_date")
    payload = {
        "hotel_id": args.hotel_id,
        "hotel_name": hotel_name,
        "snapshot_time": str(snapshot_time) if snapshot_time is not None else None,
        "total_rooms": total_rooms,
        "available_rooms": category_counts["available_rooms"],
        "sold_rooms": category_counts["occupied_rooms"],
        "occupied_rooms": category_counts["occupied_rooms"],
        "maintenance_rooms": category_counts["maintenance_rooms"],
        "dirty_rooms": category_counts["dirty_rooms"],
        "remaining_rooms": category_counts["available_rooms"],
        "occupancy_rate": occupancy_rate or 0,
        "adr": daily.get("adr", 0),
        "revpar": daily.get("revpar", 0),
        "risk_flags": ["database_mysql_read_only_snapshot"],
        "evidence": {"raw_status_counts": raw_status_counts, "metric_source": "fact_daily_metrics"},
        **freshness_metadata(data_time),
    }
    if payload.get("revpar") in (0, 0.0, None) and payload.get("adr") and payload.get("occupancy_rate"):
        payload["metric_mapping_warning"] = "RevPAR is zero or missing while ADR and occupancy exist. Check metric_aliases or imported report data."
        payload["risk_flags"].append("metric_mapping_warning_revpar")
    _append_freshness_risk(payload)
    return payload


def _query_mysql_price_snapshot(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    if _has_template_mapping(profile, "price_data"):
        return _query_mysql_business_price_snapshot(conn, args, profile)
    hotel_name = _hotel_name(profile, args.hotel_id)
    table = _table(profile, "room_fee_daily")
    columns = _columns(profile, "room_fee_daily")
    hotel_col = _col(columns, "hotel_name")
    date_col = _col(columns, "business_date")
    room_type_col = _col(columns, "room_type")
    daily_price_col = _col(columns, "daily_price")
    rack_rate_col = _col(columns, "rack_rate")
    room_fee_col = _col(columns, "room_fee")
    room_nights_col = _col(columns, "room_nights")
    order_col = _col(columns, "order_no")
    safe_table = _safe_identifier(table, "table")
    latest = _latest_date_condition(table, hotel_col, date_col)
    sql = (
        f"SELECT {_safe_identifier(room_type_col, 'column')} AS room_type, "
        f"AVG({_safe_identifier(daily_price_col, 'column')}) AS avg_daily_price, "
        f"MAX({_safe_identifier(rack_rate_col, 'column')}) AS rack_rate, "
        f"SUM({_safe_identifier(room_fee_col, 'column')}) AS room_fee, "
        f"SUM({_safe_identifier(room_nights_col, 'column')}) AS room_nights, "
        f"COUNT(DISTINCT {_safe_identifier(order_col, 'column')}) AS order_count, "
        f"MAX({_safe_identifier(date_col, 'column')}) AS business_date "
        f"FROM {safe_table} WHERE {_safe_identifier(hotel_col, 'column')} = %s AND {latest} "
        f"GROUP BY {_safe_identifier(room_type_col, 'column')} ORDER BY {_safe_identifier(room_type_col, 'column')}"
    )
    with conn.cursor() as cursor:
        cursor.execute(sql, (hotel_name, hotel_name))
        rows = cursor.fetchall()
    prices = []
    latest_business_date = None
    for row in rows:
        room_type = str(row.get("room_type") or "unknown")
        latest_business_date = latest_business_date or row.get("business_date")
        prices.append(
            {
                "room_type_id": room_type,
                "room_type_name": room_type,
                "current_price": row.get("avg_daily_price"),
                "listed_price": row.get("rack_rate"),
                "price_floor": None,
                "price_ceiling": row.get("rack_rate"),
                "available_rooms": None,
                "room_nights": row.get("room_nights"),
                "room_fee": row.get("room_fee"),
                "order_count": row.get("order_count"),
                "business_date": str(row.get("business_date")) if row.get("business_date") is not None else None,
            }
        )
    payload = {"price_snapshots": prices, "risk_flags": ["database_mysql_read_only_price_snapshot"], **freshness_metadata(latest_business_date)}
    _append_freshness_risk(payload)
    return payload


def _query_mysql_order_snapshot(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    hotel_name = _hotel_name(profile, args.hotel_id)
    table = _table(profile, "room_fee_daily")
    columns = _columns(profile, "room_fee_daily")
    hotel_col = _col(columns, "hotel_name")
    date_col = _col(columns, "business_date")
    safe_table = _safe_identifier(table, "table")
    wanted = [
        "order_no",
        "guest_name",
        "room_no",
        "room_type",
        "customer_source",
        "checkin_time",
        "checkout_time",
        "rack_rate",
        "price_type",
        "daily_price",
        "stay_type",
        "charge_subject",
        "room_nights",
        "room_fee",
        "operator_name",
        "business_date",
    ]
    projection = []
    for key in wanted:
        if key in columns:
            projection.append(f"{_safe_identifier(columns[key], 'column')} AS `{key}`")
    if not projection:
        raise KeyError("database column mapping required: room_fee_daily order fields")
    sql = (
        f"SELECT {', '.join(projection)} FROM {safe_table} "
        f"WHERE {_safe_identifier(hotel_col, 'column')} = %s "
        f"ORDER BY {_safe_identifier(date_col, 'column')} DESC, {_safe_identifier(_col(columns, 'id'), 'column')} DESC LIMIT 50"
    )
    with conn.cursor() as cursor:
        cursor.execute(sql, (hotel_name,))
        rows = cursor.fetchall()
    orders = []
    latest_business_date = None
    for row in rows:
        redacted = _redact_row(dict(row))
        latest_business_date = latest_business_date or redacted.get("business_date")
        orders.append(
            {
                "order_id": redacted.get("order_no"),
                "third_order_id": redacted.get("order_no"),
                "order_status": "reported_fee_record",
                "order_status_raw": "fact_room_fee_daily",
                "room_type_id": redacted.get("room_type"),
                "room_type_name": redacted.get("room_type"),
                "room_nights": redacted.get("room_nights"),
                "business_date": str(redacted.get("business_date")) if redacted.get("business_date") is not None else None,
                "checkin_time": str(redacted.get("checkin_time")) if redacted.get("checkin_time") is not None else None,
                "checkout_time": str(redacted.get("checkout_time")) if redacted.get("checkout_time") is not None else None,
                "payment_type": redacted.get("price_type"),
                "customer_source": redacted.get("customer_source"),
                "price_detail": {
                    "rack_rate": redacted.get("rack_rate"),
                    "daily_price": redacted.get("daily_price"),
                    "room_fee": redacted.get("room_fee"),
                    "charge_subject": redacted.get("charge_subject"),
                    "stay_type": redacted.get("stay_type"),
                },
                "privacy": {
                    "guest_name": redacted.get("guest_name"),
                    "room_no": redacted.get("room_no"),
                    "operator_name": redacted.get("operator_name"),
                },
                "risk_flags": ["database_sensitive_fields_redacted"],
            }
        )
    payload = {"orders": orders, **freshness_metadata(latest_business_date)}
    _append_freshness_risk(payload)
    return payload


def _query_mysql_reservation_snapshot(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    hotel_name = _hotel_name(profile, args.hotel_id)
    table = _table(profile, "reservation_snapshot")
    columns = _columns(profile, "reservation_snapshot")
    hotel_col = _col(columns, "hotel_name")
    date_col = _first_existing(columns, "business_date", "arrive_date", "checkin_date", "arrival_date", "prearrival_date")
    if not date_col:
        raise KeyError("database column mapping required: reservation_snapshot business/checkin date")
    room_count_col = _first_existing(columns, "room_count")
    count_col = _first_existing(columns, "room_no", "order_no", "reservation_no")
    room_type_col = _first_existing(columns, "room_type", "room_type_name")
    status_col = _first_existing(columns, "status", "order_status", "booking_status")
    safe_table = _safe_identifier(table, "table")
    if room_count_col:
        count_expr = f"SUM(COALESCE({_safe_identifier(room_count_col, 'column')}, 1)) AS new_arrival_rooms"
    elif count_col:
        count_expr = f"COUNT(DISTINCT {_safe_identifier(count_col, 'column')}) AS new_arrival_rooms"
    else:
        count_expr = "COUNT(*) AS new_arrival_rooms"
    select_parts = [count_expr, f"MAX({_safe_identifier(date_col, 'column')}) AS business_date"]
    if room_type_col:
        select_parts.append(f"{_safe_identifier(room_type_col, 'column')} AS room_type")
    base_where_parts = [
        f"{_safe_identifier(hotel_col, 'column')} = %s",
        f"DATE({_safe_identifier(date_col, 'column')}) = %s",
    ]
    base_params: list[Any] = [hotel_name, _target_date(args)]
    where_parts = list(base_where_parts)
    params: list[Any] = list(base_params)
    if status_col:
        aliases = profile.get("reservation_status_active_aliases") or ["\u9884\u8ba2", "\u5df2\u9884\u8ba2", "confirmed", "booked", "reserved"]
        placeholders = ", ".join(["%s"] * len(aliases))
        where_parts.append(f"TRIM({_safe_identifier(status_col, 'column')}) IN ({placeholders})")
        params.extend(aliases)
    group_by = f" GROUP BY {_safe_identifier(room_type_col, 'column')}" if room_type_col else ""
    sql = f"SELECT {', '.join(select_parts)} FROM {safe_table} WHERE {' AND '.join(where_parts)}{group_by}"
    with conn.cursor() as cursor:
        raw_count_sql = f"SELECT COUNT(*) AS raw_row_count FROM {safe_table} WHERE {' AND '.join(base_where_parts)}"
        cursor.execute(raw_count_sql, tuple(base_params))
        raw_row = cursor.fetchone() or {}
        raw_row_count = int(raw_row.get("raw_row_count") or 0)
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
    room_type_breakdown = []
    total = 0
    data_date = _target_date(args)
    for row in rows:
        count = int(row.get("new_arrival_rooms") or 0)
        total += count
        data_date = str(row.get("business_date") or data_date)[:10]
        if room_type_col:
            room_type_breakdown.append({"room_type": row.get("room_type"), "new_arrival_rooms": count})
    aliases = profile.get("reservation_status_active_aliases") or ["\u9884\u8ba2", "\u5df2\u9884\u8ba2", "confirmed", "booked", "reserved"]
    source_status = "ok"
    if raw_row_count == 0:
        source_status = "no_rows"
    elif total == 0:
        source_status = "status_filtered_zero"
    payload = {
        "new_arrival_rooms": total,
        "room_type_breakdown": room_type_breakdown,
        "source_table": table,
        "source_status": source_status,
        "raw_row_count": raw_row_count,
        "filtered_room_count": total,
        "status_filter_aliases": aliases,
        **freshness_metadata(data_date),
    }
    _append_freshness_risk(payload)
    return payload


def _query_mysql_stayover_snapshot(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    hotel_name = _hotel_name(profile, args.hotel_id)
    table = _table(profile, "stayover_snapshot")
    columns = _columns(profile, "stayover_snapshot")
    hotel_col = _col(columns, "hotel_name")
    room_col = _first_existing(columns, "room_no", "order_no", "guest_id")
    stayover_date_col = _first_existing(columns, "business_date", "stayover_date")
    checkout_col = _first_existing(columns, "checkout_date", "checkout_time", "curr_departure", "departure_date")
    checkin_col = _first_existing(columns, "checkin_time")
    status_col = _first_existing(columns, "status")
    room_type_col = _first_existing(columns, "room_type", "room_type_name")
    if not stayover_date_col and not checkout_col:
        raise KeyError("database column mapping required: stayover_snapshot stayover date or checkout date")
    safe_table = _safe_identifier(table, "table")
    select_parts = [
        f"COUNT(DISTINCT {_safe_identifier(room_col, 'column')}) AS stayover_rooms" if room_col else "COUNT(*) AS stayover_rooms",
    ]
    date_projection_col = stayover_date_col or checkout_col
    select_parts.append(f"MAX({_safe_identifier(date_projection_col, 'column')}) AS business_date")
    if room_type_col:
        select_parts.append(f"{_safe_identifier(room_type_col, 'column')} AS room_type")
    where_parts = [f"{_safe_identifier(hotel_col, 'column')} = %s"]
    params: list[Any] = [hotel_name]
    target_date = _target_date(args)
    if stayover_date_col:
        where_parts.append(f"DATE({_safe_identifier(stayover_date_col, 'column')}) = %s")
        params.append(target_date)
    else:
        where_parts.append(f"DATE({_safe_identifier(checkout_col, 'column')}) > %s")
        params.append(target_date)
        if checkin_col:
            where_parts.append(f"DATE({_safe_identifier(checkin_col, 'column')}) <= %s")
            params.append(target_date)
    base_where_parts = list(where_parts)
    base_params = list(params)
    if status_col:
        aliases = profile.get("stayover_status_active_aliases") or ["\u5728\u4f4f", "\u7eed\u4f4f", "\u5df2\u7eed\u4f4f", "active", "staying", "stayover"]
        placeholders = ", ".join(["%s"] * len(aliases))
        where_parts.append(f"TRIM({_safe_identifier(status_col, 'column')}) IN ({placeholders})")
        params.extend(aliases)
    group_by = f" GROUP BY {_safe_identifier(room_type_col, 'column')}" if room_type_col else ""
    sql = f"SELECT {', '.join(select_parts)} FROM {safe_table} WHERE {' AND '.join(where_parts)}{group_by}"
    with conn.cursor() as cursor:
        raw_count_sql = f"SELECT COUNT(*) AS raw_row_count FROM {safe_table} WHERE {' AND '.join(base_where_parts)}"
        cursor.execute(raw_count_sql, tuple(base_params))
        raw_row = cursor.fetchone() or {}
        raw_row_count = int(raw_row.get("raw_row_count") or 0)
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
    room_type_breakdown = []
    total = 0
    data_date = target_date
    for row in rows:
        count = int(row.get("stayover_rooms") or 0)
        total += count
        data_date = str(row.get("business_date") or data_date)[:10]
        if room_type_col:
            room_type_breakdown.append({"room_type": row.get("room_type"), "stayover_rooms": count})
    aliases = profile.get("stayover_status_active_aliases") or ["\u5728\u4f4f", "\u7eed\u4f4f", "\u5df2\u7eed\u4f4f", "active", "staying", "stayover"]
    source_status = "ok"
    if raw_row_count == 0:
        source_status = "no_rows"
    elif total == 0:
        source_status = "status_filtered_zero"
    payload = {
        "stayover_rooms": total,
        "room_type_breakdown": room_type_breakdown,
        "source_table": table,
        "source_status": source_status,
        "raw_row_count": raw_row_count,
        "filtered_room_count": total,
        "status_filter_aliases": aliases,
        **freshness_metadata(data_date),
    }
    _append_freshness_risk(payload)
    return payload


def _query_mysql_metrics(conn, args: argparse.Namespace, profile: dict[str, Any], monthly: bool = False) -> dict[str, Any]:
    hotel_name = _hotel_name(profile, args.hotel_id)
    payload = _mysql_latest_metrics(conn, profile, hotel_name, monthly=monthly, date=getattr(args, "date", None))
    payload["hotel_id"] = args.hotel_id
    payload["hotel_name"] = hotel_name
    risk_flags = list(payload.get("risk_flags") or [])
    if "database_mysql_read_only_metrics" not in risk_flags:
        risk_flags.append("database_mysql_read_only_metrics")
    payload["risk_flags"] = risk_flags
    if not monthly:
        payload.update(freshness_metadata(payload.get("data_business_date")))
        _append_freshness_risk(payload)
    return payload


def _query_mysql(args: argparse.Namespace) -> dict[str, Any]:
    config = _load_mapping_config(getattr(args, "mapping_config", None))
    profile = _profile(config, getattr(args, "profile", None))
    if not profile:
        return {
            "status": "blocked",
            "reason": "database_mapping_required",
            "db_kind": "mysql",
            "template": args.template,
            "message": "Configure HOTEL_OTA_DB_MAPPING_CONFIG and HOTEL_OTA_DB_PROFILE before using mysql templates.",
        }
    if profile.get("db_kind", "mysql") != "mysql":
        return {"status": "blocked", "reason": "database_profile_kind_mismatch", "profile": profile.get("_profile_name"), "db_kind": profile.get("db_kind")}
    conn, blocked = _connect_mysql(args, profile)
    if blocked:
        return blocked
    assert conn is not None
    with conn:
        if args.template == "operating_snapshot":
            payload = _query_mysql_operating_snapshot(conn, args, profile)
        elif args.template == "price_snapshot":
            payload = _query_mysql_price_snapshot(conn, args, profile)
        elif args.template == "order_snapshot":
            payload = _query_mysql_order_snapshot(conn, args, profile)
        elif args.template == "demand_context":
            payload = _query_mysql_demand_context(conn, args, profile)
        elif args.template == "operation_diagnosis":
            payload = _query_mysql_operation_diagnosis(conn, args, profile)
        elif args.template == "sales_baseline":
            payload = _query_mysql_sales_baseline(conn, args, profile)
        elif args.template == "daily_metrics":
            payload = _query_mysql_metrics(conn, args, profile, monthly=False)
        elif args.template == "monthly_metrics":
            payload = _query_mysql_metrics(conn, args, profile, monthly=True)
        elif args.template == "reservation_snapshot":
            payload = _query_mysql_reservation_snapshot(conn, args, profile)
        elif args.template == "stayover_snapshot":
            payload = _query_mysql_stayover_snapshot(conn, args, profile)
        else:
            raise ValueError(f"unsupported mysql template: {args.template}")
    return {
        **_source("mysql", "confirmed"),
        "template": args.template,
        "profile": profile.get("_profile_name"),
        "hotel_id": args.hotel_id,
        "payload": payload,
    }


def _query_external(args: argparse.Namespace) -> dict[str, Any]:
    missing = _missing_driver(args.db_kind)
    if missing:
        return missing
    return {
        "status": "blocked",
        "reason": "external_database_template_not_enabled",
        "db_kind": args.db_kind,
        "template": args.template,
        "message": "Postgres requires confirmed driver, DSN, and field mapping before live templates are enabled.",
    }


def database_source_enabled() -> bool:
    return os.environ.get("HOTEL_OTA_DB_SOURCE_ENABLE", "0") == "1"


def database_template_result(
    template: str,
    hotel_id: str,
    db_kind: str | None = None,
    dsn: str | None = None,
    profile: str | None = None,
    mapping_config: str | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    if template not in TEMPLATES:
        return {"status": "blocked", "reason": "unknown_template", "allowed_templates": list(TEMPLATES)}
    if os.environ.get("HOTEL_OTA_DB_READONLY", "1") != "1":
        return {"status": "blocked", "reason": "database_adapter_requires_readonly"}
    args = argparse.Namespace(
        db_kind=db_kind or os.environ.get("HOTEL_OTA_DB_KIND", "sqlite"),
        template=template,
        hotel_id=hotel_id,
        dsn=dsn,
        profile=profile,
        mapping_config=mapping_config,
        date=date,
        sql=None,
    )
    if args.db_kind == "sqlite":
        if template not in SQLITE_TEMPLATES:
            return {"status": "blocked", "reason": "sqlite_template_not_enabled", "template": template}
        payload = _query_sqlite(args)
        return {"status": "ok", **redacted_request(payload), "contract_validation": validate_contract(payload)}
    if args.db_kind == "mysql":
        try:
            result = _query_mysql(args)
        except (KeyError, ValueError) as exc:
            return {
                "status": "blocked",
                "reason": "database_mapping_invalid",
                "template": template,
                "message": "Database table or column mapping is invalid. Use real ASCII MySQL table/column names or create a view with English aliases.",
                "error_type": exc.__class__.__name__,
            }
        if result.get("status") == "blocked":
            return result
        return {"status": "ok", **redacted_request(result), "contract_validation": validate_contract(result)}
    return _query_external(args)


def database_inspect(args: argparse.Namespace) -> None:
    if args.mode not in INSPECT_MODES:
        emit({"status": "blocked", "reason": "unknown_inspect_mode", "allowed_modes": list(INSPECT_MODES)})
        return
    if os.environ.get("HOTEL_OTA_DB_READONLY", "1") != "1":
        emit({"status": "blocked", "reason": "database_adapter_requires_readonly"})
        return
    if args.db_kind != "mysql":
        emit({"status": "blocked", "reason": "inspect_only_enabled_for_mysql_v1", "db_kind": args.db_kind})
        return

    config = _load_mapping_config(getattr(args, "mapping_config", None))
    profile = _profile(config, getattr(args, "profile", None))
    conn, blocked = _connect_mysql(args, profile)
    if blocked:
        emit(blocked)
        return
    assert conn is not None
    with conn:
        with conn.cursor() as cursor:
            if args.mode == "connection":
                cursor.execute("SELECT 1 AS ok")
                cursor.fetchone()
                emit({"status": "ok", "db_kind": "mysql", "mode": "connection", "source_capability": "read_only", "profile": (profile or {}).get("_profile_name")})
                return
            if args.mode == "tables":
                cursor.execute("SHOW TABLES")
                rows = cursor.fetchall()
                tables = []
                for row in rows:
                    tables.extend(str(value) for value in row.values())
                emit({"status": "ok", "db_kind": "mysql", "mode": "tables", "tables": tables})
                return
            if not args.table:
                emit({"status": "blocked", "reason": "table_required", "mode": args.mode})
                return
            table = args.table
            _safe_identifier(table, "table")
            if args.mode == "columns":
                cursor.execute(
                    """
                    SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type, COLUMN_TYPE AS column_type, COLUMN_COMMENT AS column_comment
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                    ORDER BY ORDINAL_POSITION
                    """,
                    (table,),
                )
                emit({"status": "ok", "db_kind": "mysql", "mode": "columns", "table": table, "columns": cursor.fetchall()})
                return
            limit = max(1, min(int(args.limit or 5), 5))
            cursor.execute(f"SELECT * FROM {_safe_identifier(table, 'table')} LIMIT %s", (limit,))
            sample = [_redact_row(dict(row)) for row in cursor.fetchall()]
            emit({"status": "ok", "db_kind": "mysql", "mode": "sample", "table": table, "limit": limit, "sample": sample})


def database_query(args: argparse.Namespace) -> None:
    if args.template not in TEMPLATES:
        emit({"status": "blocked", "reason": "unknown_template", "allowed_templates": list(TEMPLATES)})
        return
    if args.sql:
        emit({"status": "blocked", "reason": "free_sql_not_allowed", "allowed_templates": list(TEMPLATES)})
        return
    if os.environ.get("HOTEL_OTA_DB_READONLY", "1") != "1":
        emit({"status": "blocked", "reason": "database_adapter_requires_readonly"})
        return
    emit(
        database_template_result(
            template=args.template,
            hotel_id=args.hotel_id,
            db_kind=args.db_kind,
            dsn=getattr(args, "dsn", None),
            profile=getattr(args, "profile", None),
            mapping_config=getattr(args, "mapping_config", None),
            date=getattr(args, "date", None),
        )
    )
