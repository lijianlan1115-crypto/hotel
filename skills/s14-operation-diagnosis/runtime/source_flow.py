from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


STATE_FILE = Path(
    os.environ.get(
        "S14_SOURCE_STATE_FILE",
        "/var/lib/hotel-ota-ai/s14-source-state.json",
    )
)
STATE_TTL_SECONDS = int(os.environ.get("S14_SOURCE_STATE_TTL_SECONDS", "600"))


def _identity(chat_id: str | None, sender_id: str | None) -> str:
    chat = str(chat_id or os.environ.get("FEISHU_CHAT_ID") or "default").strip()
    sender = str(sender_id or os.environ.get("FEISHU_SENDER_ID") or "default").strip()
    return f"{chat}:{sender}"


def _load() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _save(data: dict[str, dict[str, Any]]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_FILE)


def _purge_expired(data: dict[str, dict[str, Any]]) -> bool:
    now = time.time()
    expired = [
        key
        for key, value in data.items()
        if now - float(value.get("updated_at") or 0) > STATE_TTL_SECONDS
    ]
    for key in expired:
        data.pop(key, None)
    return bool(expired)


def set_state(
    state: str,
    *,
    chat_id: str | None = None,
    sender_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = _load()
    _purge_expired(data)
    record = {
        "state": state,
        "updated_at": time.time(),
        **(extra or {}),
    }
    data[_identity(chat_id, sender_id)] = record
    _save(data)
    return record


def get_state(
    *,
    chat_id: str | None = None,
    sender_id: str | None = None,
) -> dict[str, Any] | None:
    data = _load()
    changed = _purge_expired(data)
    if changed:
        _save(data)
    record = data.get(_identity(chat_id, sender_id))
    return dict(record) if isinstance(record, dict) else None


def clear_state(
    *,
    chat_id: str | None = None,
    sender_id: str | None = None,
) -> None:
    data = _load()
    key = _identity(chat_id, sender_id)
    if key in data:
        data.pop(key, None)
        _save(data)


def is_waiting_excel(
    *,
    chat_id: str | None = None,
    sender_id: str | None = None,
) -> bool:
    state = get_state(chat_id=chat_id, sender_id=sender_id) or {}
    return state.get("state") == "awaiting_excel"


__all__ = [
    "STATE_FILE",
    "STATE_TTL_SECONDS",
    "clear_state",
    "get_state",
    "is_waiting_excel",
    "set_state",
]
