from __future__ import annotations

import argparse
import datetime as dt
import json
from contextlib import closing
from pathlib import Path
from typing import Any

from runtime.adapters.database import database_source_enabled, database_template_result
from runtime.common import emit, json_dumps, now_local, today
from runtime.storage import connect


BUILTIN_SPECIAL_DAYS: dict[int, list[dict[str, Any]]] = {
    2026: [
        {"date": "2026-01-01", "holiday_name": "元旦", "holiday_group": "元旦", "is_off_day": True},
        {"date": "2026-02-14", "holiday_name": "春节调休上班", "holiday_group": "春节", "is_off_day": False, "is_adjusted_workday": True},
        {"date": "2026-02-17", "holiday_name": "春节", "holiday_group": "春节", "is_off_day": True},
        {"date": "2026-02-18", "holiday_name": "春节", "holiday_group": "春节", "is_off_day": True},
        {"date": "2026-02-19", "holiday_name": "春节", "holiday_group": "春节", "is_off_day": True},
        {"date": "2026-02-20", "holiday_name": "春节", "holiday_group": "春节", "is_off_day": True},
        {"date": "2026-02-21", "holiday_name": "春节", "holiday_group": "春节", "is_off_day": True},
        {"date": "2026-02-22", "holiday_name": "春节", "holiday_group": "春节", "is_off_day": True},
        {"date": "2026-02-23", "holiday_name": "春节", "holiday_group": "春节", "is_off_day": True},
        {"date": "2026-04-05", "holiday_name": "清明节", "holiday_group": "清明", "is_off_day": True},
        {"date": "2026-05-01", "holiday_name": "劳动节", "holiday_group": "劳动节", "is_off_day": True},
        {"date": "2026-05-02", "holiday_name": "劳动节", "holiday_group": "劳动节", "is_off_day": True},
        {"date": "2026-06-19", "holiday_name": "端午节", "holiday_group": "端午", "is_off_day": True},
        {"date": "2026-09-25", "holiday_name": "中秋节", "holiday_group": "中秋", "is_off_day": True},
        {"date": "2026-10-01", "holiday_name": "国庆节", "holiday_group": "国庆", "is_off_day": True},
        {"date": "2026-10-02", "holiday_name": "国庆节", "holiday_group": "国庆", "is_off_day": True},
        {"date": "2026-10-03", "holiday_name": "国庆节", "holiday_group": "国庆", "is_off_day": True},
    ]
}


def _date(value: str | None) -> dt.date:
    return dt.date.fromisoformat(value or today())


def _daterange(start: dt.date, end: dt.date):
    current = start
    while current <= end:
        yield current
        current += dt.timedelta(days=1)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "是"}
    return False


def _normalize_seed_item(item: dict[str, Any], source: str) -> dict[str, Any]:
    date_value = item.get("date") or item.get("day") or item.get("dt")
    if not date_value:
        raise ValueError("holiday seed item requires date")
    is_off_day = item.get("is_off_day")
    if is_off_day is None:
        is_off_day = item.get("isOffDay")
    if is_off_day is None:
        is_off_day = item.get("is_holiday")
    is_adjusted = item.get("is_adjusted_workday")
    if is_adjusted is None:
        is_adjusted = item.get("isAdjustedWorkday")
    normalized_off = _bool(is_off_day)
    normalized_adjusted = _bool(is_adjusted) or not normalized_off
    holiday_name = item.get("holiday_name") or item.get("name") or item.get("localName") or item.get("note")
    return {
        "date": str(date_value)[:10],
        "holiday_name": holiday_name,
        "holiday_group": item.get("holiday_group") or holiday_name,
        "is_off_day": normalized_off,
        "is_holiday": normalized_off,
        "is_adjusted_workday": normalized_adjusted and not normalized_off,
        "source": item.get("source") or source,
    }


def load_holiday_seed(year: int, seed_file: str | None = None) -> dict[str, dict[str, Any]]:
    source = "builtin_project_seed"
    raw: Any = {"days": BUILTIN_SPECIAL_DAYS.get(year, [])}
    if seed_file:
        source = f"seed_file:{Path(seed_file).name}"
        with open(seed_file, "r", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = raw.get("days") or raw.get("holidays") or raw.get("data") or []
    else:
        items = []
    seed: dict[str, dict[str, Any]] = {}
    for item in items:
        normalized = _normalize_seed_item(dict(item), source)
        if dt.date.fromisoformat(normalized["date"]).year == year:
            seed[normalized["date"]] = normalized
    return seed


def _tags_for(date_value: dt.date, special: dict[str, Any] | None, next_delta: int | None, prev_delta: int | None) -> dict[str, Any]:
    weekday = date_value.weekday()
    is_weekend = weekday >= 5
    is_adjusted = bool((special or {}).get("is_adjusted_workday"))
    is_holiday = bool((special or {}).get("is_holiday"))
    is_off_day = bool((special or {}).get("is_off_day")) or (is_weekend and not is_adjusted)
    is_workday = is_adjusted or not is_off_day
    month = date_value.month
    if is_adjusted:
        demand_level = "low_or_normal"
        price_advice = "调休上班日，不按普通周末高价。"
    elif is_holiday:
        demand_level = "high_candidate"
        price_advice = "法定假期需求候选，仍需结合今日经营和进度。"
    elif is_weekend:
        demand_level = "medium_candidate"
        price_advice = "周末需求候选，不能单独触发涨价。"
    else:
        demand_level = "normal"
        price_advice = "普通工作日，按实时经营数据判断。"
    if is_holiday:
        season_tag = "holiday_peak"
    elif next_delta is not None and 0 < next_delta <= 3:
        season_tag = "holiday_warmup"
    elif prev_delta is not None and 0 < prev_delta <= 2:
        season_tag = "holiday_cooldown"
    elif month in {7, 8}:
        season_tag = "summer_vacation"
    elif month in {1, 2}:
        season_tag = "winter_vacation"
    else:
        season_tag = "normal"
    school_vacation_tag = "summer_vacation" if month in {7, 8} else "winter_vacation" if month in {1, 2} else "none"
    return {
        "weekday": weekday + 1,
        "is_weekend": is_weekend,
        "is_workday": is_workday,
        "is_holiday": is_holiday,
        "is_adjusted_workday": is_adjusted,
        "is_off_day": is_off_day,
        "season_tag": season_tag,
        "school_vacation_tag": school_vacation_tag,
        "demand_level": demand_level,
        "price_advice": price_advice,
    }


def build_calendar_days(year: int, seed_file: str | None = None) -> list[dict[str, Any]]:
    seed = load_holiday_seed(year, seed_file)
    start = dt.date(year, 1, 1)
    end = dt.date(year, 12, 31)
    holiday_dates = sorted(dt.date.fromisoformat(day) for day, item in seed.items() if item.get("is_holiday"))
    rows: list[dict[str, Any]] = []
    for date_value in _daterange(start, end):
        next_holiday = min((holiday for holiday in holiday_dates if holiday >= date_value), default=None)
        prev_holiday = max((holiday for holiday in holiday_dates if holiday <= date_value), default=None)
        next_delta = (next_holiday - date_value).days if next_holiday else None
        prev_delta = (date_value - prev_holiday).days if prev_holiday else None
        special = seed.get(date_value.isoformat())
        tags = _tags_for(date_value, special, next_delta, prev_delta)
        rows.append(
            {
                "date": date_value.isoformat(),
                "year": date_value.year,
                "month": date_value.month,
                "day": date_value.day,
                "days_to_holiday": next_delta,
                "days_after_holiday": prev_delta,
                "holiday_name": (special or {}).get("holiday_name"),
                "holiday_group": (special or {}).get("holiday_group"),
                "source_quality": "confirmed" if special else "computed",
                "source": (special or {}).get("source") or "runtime_date_algorithm",
                "updated_at": now_local(),
                **tags,
            }
        )
    return rows


def _ensure_calendar_tables(db_path: str) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            conn.executescript(
                """
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
                """
            )


def sync_calendar_year(db_path: str, year: int, seed_file: str | None = None) -> dict[str, Any]:
    _ensure_calendar_tables(db_path)
    rows = build_calendar_days(year, seed_file)
    with closing(connect(db_path)) as conn:
        with conn:
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO calendar_days (
                      date, year, month, day, weekday, is_weekend, is_workday, is_holiday,
                      is_adjusted_workday, is_off_day, holiday_name, holiday_group,
                      days_to_holiday, days_after_holiday, season_tag, school_vacation_tag,
                      local_event_count, event_heat_level, demand_level, price_advice,
                      source_quality, source, updated_at
                    )
                    VALUES (
                      :date, :year, :month, :day, :weekday, :is_weekend, :is_workday, :is_holiday,
                      :is_adjusted_workday, :is_off_day, :holiday_name, :holiday_group,
                      :days_to_holiday, :days_after_holiday, :season_tag, :school_vacation_tag,
                      0, 'none', :demand_level, :price_advice,
                      :source_quality, :source, :updated_at
                    )
                    ON CONFLICT(date) DO UPDATE SET
                      year=excluded.year,
                      month=excluded.month,
                      day=excluded.day,
                      weekday=excluded.weekday,
                      is_weekend=excluded.is_weekend,
                      is_workday=excluded.is_workday,
                      is_holiday=excluded.is_holiday,
                      is_adjusted_workday=excluded.is_adjusted_workday,
                      is_off_day=excluded.is_off_day,
                      holiday_name=excluded.holiday_name,
                      holiday_group=excluded.holiday_group,
                      days_to_holiday=excluded.days_to_holiday,
                      days_after_holiday=excluded.days_after_holiday,
                      season_tag=excluded.season_tag,
                      school_vacation_tag=excluded.school_vacation_tag,
                      demand_level=excluded.demand_level,
                      price_advice=excluded.price_advice,
                      source_quality=excluded.source_quality,
                      source=excluded.source,
                      updated_at=excluded.updated_at
                    """,
                    {key: int(value) if isinstance(value, bool) else value for key, value in row.items()},
                )
    return {"status": "ok", "year": year, "rows": len(rows), "seed_file": seed_file, "updated_at": now_local()}


def _row_to_calendar_context(row: Any) -> dict[str, Any]:
    result = dict(row)
    for key in ("is_weekend", "is_workday", "is_holiday", "is_adjusted_workday", "is_off_day"):
        result[key] = bool(result.get(key))
    return result


def get_calendar_day(db_path: str, date_text: str) -> dict[str, Any]:
    date_value = _date(date_text)
    _ensure_calendar_tables(db_path)
    with closing(connect(db_path)) as conn:
        row = conn.execute("SELECT * FROM calendar_days WHERE date=?", (date_value.isoformat(),)).fetchone()
    if row is None:
        sync_calendar_year(db_path, date_value.year)
        with closing(connect(db_path)) as conn:
            row = conn.execute("SELECT * FROM calendar_days WHERE date=?", (date_value.isoformat(),)).fetchone()
    if row is None:
        raise ValueError(f"calendar row not found: {date_value.isoformat()}")
    return _row_to_calendar_context(row)


def calendar_sync(args: argparse.Namespace) -> None:
    emit(sync_calendar_year(args.db, args.year, args.seed_file))


def calendar_query(args: argparse.Namespace) -> None:
    context = get_calendar_day(args.db, args.date)
    emit({"status": "ok", **context, "approval_allowed": False})


def _load_json_file(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _canonical_weather_provider(provider: str) -> str:
    aliases = {
        "wttr_mcp": "wttr_http",
        "sample": "weather_fixture",
        "manual": "manual_weather",
    }
    return aliases.get(provider or "weather_mcp", provider or "weather_mcp")


def _weather_source_quality(provider: str) -> str:
    if provider == "weather_mcp":
        return "confirmed"
    if provider in {"wttr_http", "amap_api", "qweather_api"}:
        return "secondary"
    if provider == "weather_fixture":
        return "fixture"
    if provider == "manual_weather":
        return "manual"
    return "secondary"


def normalize_weather(payload: dict[str, Any] | None, provider: str = "weather_mcp") -> dict[str, Any]:
    provider = _canonical_weather_provider(provider)
    if not payload:
        summary = "天气 MCP 未配置或未返回。" if provider == "weather_mcp" else f"{provider} 天气源未配置或未返回。"
        return {
            "status": "unavailable",
            "source": provider,
            "weather_summary": summary,
            "weather_risk_level": "unknown",
            "source_quality": "unavailable",
            "field_quality": "missing",
        }
    if payload.get("status") in {"timeout", "error", "unavailable"}:
        return {
            "status": "unavailable",
            "source": provider,
            "weather_summary": payload.get("message") or f"{provider} 天气源超时或不可用。",
            "weather_risk_level": "unknown",
            "source_quality": "unavailable",
            "field_quality": "missing",
        }
    current = (payload.get("current_condition") or [{}])[0] if isinstance(payload.get("current_condition"), list) else payload
    desc = payload.get("weather_summary") or payload.get("description")
    if not desc:
        weather_desc = current.get("weatherDesc") or []
        if weather_desc and isinstance(weather_desc, list):
            desc = (weather_desc[0] or {}).get("value")
    temp = current.get("temp_C") or current.get("temperature")
    precip = current.get("precipMM") or current.get("precipitation")
    summary_parts = [str(desc or "天气已返回")]
    if temp not in (None, ""):
        summary_parts.append(f"{temp}C")
    weather_text = " ".join(summary_parts)
    risk = "low"
    text = weather_text.lower()
    try:
        precip_value = float(precip or 0)
    except (TypeError, ValueError):
        precip_value = 0.0
    if any(word in text for word in ("storm", "暴雨", "大雨", "snow", "雪", "雷")) or precip_value >= 10:
        risk = "high"
    elif any(word in text for word in ("rain", "雨", "fog", "雾", "阴")) or precip_value > 0:
        risk = "medium"
    return {
        "status": "ok",
        "source": provider,
        "weather_summary": weather_text,
        "weather_risk_level": risk,
        "source_quality": _weather_source_quality(provider),
        "field_quality": "confirmed" if desc else "inferred",
        "data_snapshot_time": now_local(),
    }


def _fresh_operating_context(payload: dict[str, Any] | None) -> tuple[bool, dict[str, Any]]:
    if not payload:
        return False, {"status": "missing", "freshness_status": "missing_date"}
    context = {
        "status": payload.get("status") or "ok",
        "freshness_status": payload.get("freshness_status"),
        "business_status": payload.get("business_status"),
        "data_business_date": payload.get("data_business_date"),
        "data_snapshot_time": payload.get("data_snapshot_time"),
    }
    fresh = context["freshness_status"] == "fresh" and context["business_status"] == "current"
    return fresh, context


def _fresh_progress_context(payload: dict[str, Any] | None) -> tuple[bool, dict[str, Any]]:
    if not payload:
        return False, {"status": "missing", "freshness_status": "missing_date", "downstream_allowed": False}
    context = {
        "status": payload.get("status") or "ok",
        "freshness_status": payload.get("freshness_status"),
        "business_status": payload.get("business_status"),
        "downstream_allowed": bool(payload.get("downstream_allowed")),
        "actual_source": payload.get("actual_source"),
        "target_source": payload.get("target_source"),
    }
    return context["freshness_status"] == "fresh" and context["downstream_allowed"], context


def market_context(args: argparse.Namespace) -> None:
    business_date = args.date or today()
    calendar_context = get_calendar_day(args.db, business_date)
    weather_provider = args.weather_provider
    if args.weather_fixture and weather_provider == "weather_mcp":
        weather_provider = "weather_fixture"
    weather_context = normalize_weather(_load_json_file(args.weather_fixture), weather_provider)
    operating_payload = _load_json_file(args.operating_fixture)
    if operating_payload is None and database_source_enabled():
        db_result = database_template_result("operating_snapshot", args.hotel_id, date=business_date)
        operating_payload = (db_result.get("payload") or {}) if db_result.get("status") == "ok" else None
    operating_fresh, operating_context = _fresh_operating_context(operating_payload)
    progress_fresh, progress_context = _fresh_progress_context(_load_json_file(args.progress_fixture))
    weather_available = weather_context.get("status") == "ok"
    downstream_allowed = (
        calendar_context.get("source_quality") in {"confirmed", "computed"}
        and weather_available
        and operating_fresh
        and progress_fresh
    )
    blocked_reason = None
    if not weather_available:
        blocked_reason = "weather_context_unavailable"
    if not operating_fresh or not progress_fresh:
        blocked_reason = "missing_fresh_operating_progress"
    if calendar_context.get("is_adjusted_workday"):
        demand_signal = "neutral"
    elif calendar_context.get("is_holiday") and downstream_allowed:
        demand_signal = "strong"
    elif weather_context.get("weather_risk_level") in {"medium", "high"}:
        demand_signal = "cautious"
    else:
        demand_signal = "neutral"
    emit(
        {
            "status": "ok" if downstream_allowed else "data_gap",
            "hotel_id": args.hotel_id,
            "business_date": business_date,
            "calendar_context": calendar_context,
            "weather_context": weather_context,
            "event_context": {"status": "not_enabled_v1", "local_event_count": calendar_context.get("local_event_count", 0)},
            "competitor_context": {"status": "s7_aggregate_pending"},
            "operating_context": operating_context,
            "progress_context": progress_context,
            "demand_signal": demand_signal,
            "source_quality": "mixed" if weather_available else "calendar_only",
            "freshness_status": "fresh" if downstream_allowed else "missing_date",
            "data_snapshot_time": now_local(),
            "downstream_allowed": downstream_allowed,
            "downstream_blocked_reason": None if downstream_allowed else blocked_reason,
            "approval_allowed": False,
            "next_skill": "S5" if downstream_allowed else "S14",
        }
    )


def event_discover(args: argparse.Namespace) -> None:
    _ensure_calendar_tables(args.db)
    fixture = _load_json_file(args.fixture_file)
    if not fixture:
        emit(
            {
                "status": "data_gap",
                "hotel_id": args.hotel_id,
                "date_range": args.date_range,
                "reason": "event_discovery_provider_not_configured",
                "source_capability": "pending_mcp_or_search",
                "events_imported": 0,
            }
        )
        return
    events = fixture.get("events") if isinstance(fixture, dict) else fixture
    if not isinstance(events, list):
        events = []
    with closing(connect(args.db)) as conn:
        with conn:
            for item in events:
                conn.execute(
                    """
                    INSERT INTO event_candidates (
                      hotel_id, date, event_name, event_type, location, distance_km,
                      source_url, confidence, expected_heat, status, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        args.hotel_id,
                        item.get("date"),
                        item.get("event_name") or item.get("name") or "unknown_event",
                        item.get("event_type"),
                        item.get("location"),
                        item.get("distance_km"),
                        item.get("source_url"),
                        float(item.get("confidence") or 0),
                        item.get("expected_heat") or "unknown",
                        item.get("status") or "candidate",
                        now_local(),
                    ),
                )
    emit({"status": "ok", "hotel_id": args.hotel_id, "events_imported": len(events)})
