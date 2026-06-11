from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from typing import Any

from runtime.common import DEFAULT_BASE_URL, emit, now_local, parse_json_input, redacted_request
from runtime.storage import log_api


def canonical_sign_string(params: dict[str, Any], app_key: str) -> str:
    items = []
    for key in sorted(k for k in params.keys() if k != "Sign"):
        items.append(f"{key}={params[key]}")
    return "&".join(items) + app_key


def sign_request(params: dict[str, Any], app_key: str, sign_type: str) -> str:
    raw = canonical_sign_string(params, app_key)
    algo = sign_type.upper()
    if algo == "MD5":
        return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()
    if algo == "SHA256":
        return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()
    raise ValueError(f"unsupported SignType: {sign_type}")


def build_beyondh_request(method: str, biz_content: dict[str, Any]) -> dict[str, Any]:
    channel_key = os.environ.get("BEYONDH_CHANNEL_KEY", "")
    app_key = os.environ.get("BEYONDH_APP_KEY", "")
    sign_type = os.environ.get("BEYONDH_SIGN_TYPE", "MD5").upper()
    params: dict[str, Any] = {
        "ChannelKey": channel_key,
        "Method": method,
        "BizContent": json.dumps(biz_content, ensure_ascii=False, separators=(",", ":")),
        "SignType": sign_type,
        "Format": "json",
        "Charset": "utf-8",
        "Version": "1.0",
        "Timestamp": now_local(),
    }
    if channel_key and app_key:
        params["Sign"] = sign_request(params, app_key, sign_type)
    else:
        params["Sign"] = "MISSING_CHANNEL_KEY_OR_APP_KEY"
    return params


def beyondh_call(args: argparse.Namespace) -> None:
    biz = parse_json_input(args.biz_content, getattr(args, "biz_content_b64", None))
    request_body = build_beyondh_request(args.method, biz)
    domain = os.environ.get("BEYONDH_DOMAIN", "")
    summary = {
        "adapter_vendor": "beyondh",
        "channel_source": "pms",
        "data_source_type": "beyondh_api",
        "source_capability": "write_dry_run" if (args.dry_run or os.environ.get("BEYONDH_ENABLE_LIVE") != "1") else "write_live_pending",
        "field_quality": "confirmed" if os.environ.get("BEYONDH_CHANNEL_KEY") else "manual_required",
        "captured_at": now_local(),
        "method": args.method,
        "body": redacted_request(request_body),
        "domain": domain,
    }
    if args.dry_run or os.environ.get("BEYONDH_ENABLE_LIVE") != "1":
        if not getattr(args, "no_log", False):
            log_api(args.hotel_id, args.method, summary, {"dry_run": True}, "dry_run", args.db)
        emit({"status": "dry_run", "request": summary, "message": "Set BEYONDH_ENABLE_LIVE=1 and omit --dry-run for live call."})
        return

    url = DEFAULT_BASE_URL.rstrip("/")
    data = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "domain": domain})
    with urllib.request.urlopen(req, timeout=args.timeout) as resp:
        response_text = resp.read().decode("utf-8")
    try:
        response_json = json.loads(response_text)
    except json.JSONDecodeError:
        response_json = {"raw": response_text}
    status = "ok" if response_json.get("Code") == 10000 else "error"
    log_api(args.hotel_id, args.method, summary, response_json, status, args.db)
    emit({"status": status, "response": response_json})
