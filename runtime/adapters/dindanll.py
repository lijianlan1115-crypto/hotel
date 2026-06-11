from __future__ import annotations

import datetime as dt
import os
from typing import Any

from runtime.common import DINDANLL_BASE_URL, compact_json, source_meta


DINDANLL_ORDER_STATUS = {
    16: "pending_confirmation",
    21: "confirmed",
    26: "rejected",
    36: "reserved",
    51: "cancelled",
    61: "abnormal",
}


def dindanll_signature_content(params: dict[str, Any]) -> str:
    return "&".join(f"{key}={params[key]}" for key in sorted(params))


def build_dindanll_request(path: str, biz_content: dict[str, Any]) -> dict[str, Any]:
    app_code = os.environ.get("DINDANLL_APP_CODE", "")
    auth_access_token = os.environ.get("DINDANLL_AUTH_ACCESS_TOKEN", "")
    version = os.environ.get("DINDANLL_VERSION", "3.0")
    timestamp = str(int(dt.datetime.now().timestamp() * 1000))
    req_body = compact_json(biz_content)
    sign_params = {
        "appCode": app_code,
        "timestamp": timestamp,
        "version": version,
        "reqBody": req_body,
    }
    signature_content = dindanll_signature_content(sign_params)
    sign = "RSA2_SIGNATURE_REQUIRED" if app_code else "MISSING_APP_CODE_OR_RSA_PRIVATE_KEY"
    return {
        "method": "POST",
        "url": DINDANLL_BASE_URL.rstrip("/") + "/" + path.lstrip("/"),
        "content_type": "application/json",
        "headers": {
            "Content-Type": "application/json",
            "version": version,
            "appCode": app_code,
            "timestamp": timestamp,
            "sign": sign,
        },
        "query": {
            "appCode": app_code,
            "authAccessToken": auth_access_token,
        },
        "body": biz_content,
        "signature_content": signature_content,
        "sign_note": "订单来了使用 RSA2/SHA1withRSA；当前工程包仅做 dry-run 和签名原文构造，不做真实签名调用。",
    }


def normalize_dindanll_price_sample() -> dict[str, Any]:
    raw = {
        "code": "0",
        "data": {
            "hotelNum": 10001,
            "currency": "CNY",
            "amountRoomTypeList": [
                {
                    "roomTypeCode": 9001,
                    "amountDateList": [{"date": "2026-06-02", "sellingAmount": 159, "reserveAmount": 139}],
                }
            ],
        },
    }
    price_rows = []
    for room in raw["data"]["amountRoomTypeList"]:
        for row in room["amountDateList"]:
            price_rows.append(
                {
                    "room_type_id": str(room["roomTypeCode"]),
                    "business_date": row["date"],
                    "current_price": row["sellingAmount"],
                    "listed_price": row["sellingAmount"],
                    "promotion_price": None,
                    "net_price_after_activity": row["sellingAmount"],
                    "platform_prepaid_price": None,
                    "price_floor": row["reserveAmount"],
                    "price_ceiling": None,
                    "activity_labels": [],
                }
            )
    return {
        **source_meta("dindanll", "pms", "dindanll_api", "read_only", "confirmed"),
        "object_type": "price_snapshot",
        "source_api": "/open/pms/third/ari/price",
        "hotel_id": str(raw["data"]["hotelNum"]),
        "currency": raw["data"]["currency"],
        "price_snapshots": price_rows,
        "raw_summary": {"code": raw["code"]},
    }


def normalize_dindanll_inventory_sample() -> dict[str, Any]:
    raw = {
        "code": "0",
        "data": {
            "hotelNum": 10001,
            "invList": [
                {
                    "roomTypeCode": 9001,
                    "invDateList": [{"date": "2026-06-02", "remain": 3, "status": 10}],
                }
            ],
        },
    }
    inv = raw["data"]["invList"][0]
    row = inv["invDateList"][0]
    return {
        **source_meta("dindanll", "pms", "dindanll_api", "read_only", "confirmed"),
        "object_type": "operating_snapshot",
        "source_api": "/open/pms/third/ari/inv",
        "hotel_id": str(raw["data"]["hotelNum"]),
        "business_date": row["date"],
        "room_type_id": str(inv["roomTypeCode"]),
        "remaining_rooms": row["remain"],
        "room_status": "open" if row["status"] == 10 else "closed_or_unset",
        "risk_flags": [] if row["status"] == 10 else ["room_type_not_open"],
        "raw_summary": {"code": raw["code"], "status": row["status"]},
    }


def normalize_dindanll_order_sample() -> dict[str, Any]:
    raw = {
        "code": "0",
        "data": {
            "thirdOrderNum": "MT202606020001",
            "orderNum": "DDLL202606020001",
            "boolFlashLive": True,
            "orderStatus": 36,
            "hotelNum": 10001,
            "roomTypeCode": 9001,
            "paymentType": 15,
            "numberOfUnit": 1,
            "checkinTime": "2026-06-02 14:00:00",
            "checkoutTime": "2026-06-03 12:00:00",
            "dateAmountList": [{"date": "2026-06-02", "sellingAmount": 159, "reserveAmount": 139}],
        },
    }
    data = raw["data"]
    return {
        **source_meta("dindanll", "pms", "dindanll_api", "read_only", "confirmed"),
        "object_type": "order_snapshot",
        "source_api": "/open/pms/third/order/get",
        "hotel_id": str(data["hotelNum"]),
        "order_id": data["orderNum"],
        "third_order_id": data["thirdOrderNum"],
        "order_status": DINDANLL_ORDER_STATUS.get(data["orderStatus"], "unknown"),
        "order_status_raw": data["orderStatus"],
        "room_type_id": str(data["roomTypeCode"]),
        "room_nights": data["numberOfUnit"],
        "checkin_time": data["checkinTime"],
        "checkout_time": data["checkoutTime"],
        "payment_type": "prepaid" if data["paymentType"] == 15 else "pay_at_hotel",
        "price_detail": data["dateAmountList"],
        "risk_flags": [] if data["orderStatus"] in (21, 36) else ["order_not_reserved"],
        "raw_summary": {"code": raw["code"]},
    }
