from __future__ import annotations

import datetime as dt
import hashlib
import os
from typing import Any

from runtime.common import MEITUAN_BASE_URL, compact_json, source_meta


MEITUAN_RES_STATUS = {
    "S": "book_success",
    "R": "rejected_or_failed",
    "P": "pending_confirmation",
    "C": "cancelled",
}


def meituan_signature_content(params: dict[str, Any], sign_key: str) -> str:
    parts = []
    for key in sorted(params):
        if key == "sign":
            continue
        value = params[key]
        if value in (None, ""):
            continue
        parts.append(f"{key}{value}")
    return sign_key + "".join(parts)


def sign_meituan_request(params: dict[str, Any], sign_key: str) -> str:
    raw = meituan_signature_content(params, sign_key)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def build_meituan_request(path: str, biz_content: dict[str, Any], business_id: int = 57) -> dict[str, Any]:
    developer_id = os.environ.get("MEITUAN_DEVELOPER_ID", "")
    sign_key = os.environ.get("MEITUAN_SIGN_KEY", "")
    app_auth_token = os.environ.get("MEITUAN_APP_AUTH_TOKEN", "")
    params: dict[str, Any] = {
        "appAuthToken": app_auth_token,
        "businessId": business_id,
        "charset": "utf-8",
        "developerId": developer_id,
        "timestamp": str(int(dt.datetime.now().timestamp())),
        "version": "2",
        "biz": compact_json(biz_content),
    }
    if developer_id and sign_key:
        params["sign"] = sign_meituan_request(params, sign_key)
        signature_content = "redacted"
    else:
        params["sign"] = "MISSING_DEVELOPER_ID_OR_SIGN_KEY"
        signature_content = "MISSING_DEVELOPER_ID_OR_SIGN_KEY"
    return {
        "method": "POST",
        "url": MEITUAN_BASE_URL.rstrip("/") + "/" + path.lstrip("/"),
        "content_type": "application/x-www-form-urlencoded;charset=utf-8",
        "params": params,
        "signature_content": signature_content,
    }


def normalize_meituan_price_sample() -> dict[str, Any]:
    raw = {
        "code": "OP_SUCCESS",
        "data": {
            "code": 10000,
            "data": {
                "roomTypeId": "123451512",
                "customerCategory": "Normal",
                "dailyPrice": [{"date": "2026-06-02", "originPrice": "120", "actualPrice": "90"}],
            },
        },
    }
    price_rows = []
    for row in raw["data"]["data"]["dailyPrice"]:
        listed_price = float(row["originPrice"])
        promotion_price = float(row["actualPrice"])
        price_rows.append(
            {
                "room_type_id": raw["data"]["data"]["roomTypeId"],
                "business_date": row["date"],
                "current_price": promotion_price,
                "listed_price": listed_price,
                "promotion_price": promotion_price,
                "net_price_after_activity": promotion_price,
                "platform_prepaid_price": None,
                "price_floor": None,
                "price_ceiling": None,
                "activity_labels": ["meituan_sample_discount"] if promotion_price < listed_price else [],
            }
        )
    return {
        **source_meta("meituan", "meituan", "meituan_api", "read_only", "confirmed"),
        "object_type": "price_snapshot",
        "source_api": "/pms/priceinve/getRoomPrice",
        "price_snapshots": price_rows,
        "raw_summary": {"outer_code": raw["code"], "business_code": raw["data"]["code"]},
    }


def normalize_meituan_room_count_sample() -> dict[str, Any]:
    raw = {
        "code": "OP_SUCCESS",
        "data": {
            "code": 10000,
            "data": [
                {
                    "roomTypeId": "KING",
                    "channel": "MeiTuanEBK",
                    "businessDate": "2026-06-02",
                    "totalCount": 10,
                    "saleableCount": 8,
                    "remainingCount": 3,
                    "soldCount": 5,
                    "overBookingCount": 0,
                    "saleableWithOverBookingCount": 8,
                    "hasChannelQuota": True,
                    "physicalExclusiveCount": 0,
                }
            ],
        },
    }
    row = raw["data"]["data"][0]
    total = int(row["totalCount"] or 0)
    sold = int(row["soldCount"] or 0)
    occupancy_rate = round(sold / total, 4) if total else None
    return {
        **source_meta("meituan", "meituan", "meituan_api", "read_only", "confirmed"),
        "object_type": "operating_snapshot",
        "source_api": "/pms/priceinve/getRoomCount",
        "business_date": row["businessDate"],
        "room_type_id": row["roomTypeId"],
        "room_total": total,
        "available_rooms": row["saleableCount"],
        "sold_rooms": sold,
        "remaining_rooms": row["remainingCount"],
        "occupancy_rate": occupancy_rate,
        "risk_flags": ["has_channel_quota"] if row["hasChannelQuota"] else [],
        "raw_summary": {"outer_code": raw["code"], "business_code": raw["data"]["code"]},
    }
