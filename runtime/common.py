from __future__ import annotations

import base64
import datetime as dt
import decimal
import json
import os
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = os.environ.get(
    "HOTEL_OTA_DB",
    str(PACKAGE_ROOT / "data" / "hotel_ops.sqlite") if os.name == "nt" else "/var/lib/hotel-ota-ai/hotel_ops.sqlite",
)
DEFAULT_LOG_DIR = os.environ.get(
    "HOTEL_OTA_LOG_DIR",
    str(PACKAGE_ROOT / "logs") if os.name == "nt" else "/var/log/hotel-ota-ai",
)
DEFAULT_BASE_URL = os.environ.get("BEYONDH_BASE_URL", "https://openapi.beyondh.com")
MEITUAN_BASE_URL = os.environ.get("MEITUAN_BASE_URL", "https://api-open-cater.meituan.com")
DINDANLL_BASE_URL = os.environ.get("DINDANLL_BASE_URL", "https://open.dingdanll.com")

SECRET_KEYS = {
    "Sign",
    "sign",
    "ChannelKey",
    "appAuthToken",
    "authAccessToken",
    "appSecret",
    "signKey",
    "privateKey",
    "publicKey",
    "signature_content",
    "ticket",
    "token",
}


def now_local() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return dt.date.today().isoformat()


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default))


def json_default(value: Any) -> Any:
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    return str(value)


def json_dumps(value: Any, **kwargs: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=json_default, **kwargs)


def compact_json(value: Any) -> str:
    return json_dumps(value, separators=(",", ":"))


def source_meta(
    adapter_vendor: str,
    channel_source: str,
    data_source_type: str,
    source_capability: str,
    field_quality: str,
) -> dict[str, Any]:
    return {
        "adapter_vendor": adapter_vendor,
        "channel_source": channel_source,
        "data_source_type": data_source_type,
        "source_capability": source_capability,
        "field_quality": field_quality,
        "captured_at": now_local(),
    }


def parse_json_input(value: str | None = None, value_b64: str | None = None) -> dict[str, Any]:
    if value_b64:
        decoded = base64.b64decode(value_b64).decode("utf-8")
        return json.loads(decoded)
    return json.loads(value or "{}")


def redact_value(key: str, value: Any) -> Any:
    if key not in SECRET_KEYS:
        return value
    if value in (
        None,
        "",
        "MISSING_CHANNEL_KEY_OR_APP_KEY",
        "MISSING_DEVELOPER_ID_OR_SIGN_KEY",
        "MISSING_APP_CODE_OR_RSA_PRIVATE_KEY",
        "RSA2_SIGNATURE_REQUIRED",
    ):
        return value
    text = str(value)
    if len(text) <= 8:
        return "***"
    return text[:4] + "***" + text[-4:]


def redacted_request(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: redacted_request(redact_value(key, item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redacted_request(item) for item in value]
    return value
