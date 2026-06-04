"""Bot status assembly from Redis + Postgres (backend doc §9.2)."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from apps.api.repositories import event_repository
from packages.messaging import state_keys


def _decode(raw: Any, default: Any = None) -> Any:
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


def _heartbeat_to_iso(raw: Any) -> str | None:
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return None


async def get_status(redis: Any, session_factory: Any, settings: Any) -> dict:
    try:
        status = await redis.get(state_keys.BOT_STATUS)
        mode = await redis.get(state_keys.BOT_MODE)
        hb = await redis.get(state_keys.BOT_HEARTBEAT)
        risk = await redis.get(state_keys.BOT_RISK_STATUS)
        protection = await redis.get(state_keys.BOT_PROTECTION_STATUS)
        reconciliation = await redis.get(state_keys.BOT_RECONCILIATION_STATUS)
    except Exception:  # noqa: BLE001 - Redis down => degraded (§21.1)
        return {
            "state": "UNKNOWN", "mode": None, "heartbeat_at": None,
            "is_alive": False, "is_trading_enabled": False,
            "risk_status": "UNKNOWN", "protection_status": "UNKNOWN",
            "reconciliation_status": "UNKNOWN", "last_event": None,
            "degraded": True,
        }

    is_alive = False
    if hb:
        try:
            age_ms = int(time.time() * 1000) - int(hb)
            is_alive = age_ms <= settings.heartbeat_alive_sec * 1000
        except (ValueError, TypeError):
            is_alive = False

    state = status if (status and is_alive) else (status or "UNKNOWN")
    if status and not is_alive:
        state = "DISCONNECTED"

    last_event = None
    try:
        ev = await event_repository.latest(session_factory)
        if ev:
            last_event = {"event_type": ev.get("type"), "message": ev.get("message")}
    except Exception:  # noqa: BLE001 - DB optional for status
        last_event = None

    return {
        "state": state,
        "mode": mode,
        "heartbeat_at": _heartbeat_to_iso(hb),
        "is_alive": is_alive,
        "is_trading_enabled": state == "RUNNING",
        "risk_status": _decode(risk, "NORMAL"),
        "protection_status": _decode(protection, "OK"),
        "reconciliation_status": _decode(reconciliation, "OK"),
        "last_event": last_event,
    }


async def raw_state(redis: Any, heartbeat_alive_sec: int = 15) -> tuple[str | None, bool]:
    """Return (state, is_alive) for command validation. Redis errors propagate."""
    status = await redis.get(state_keys.BOT_STATUS)
    hb = await redis.get(state_keys.BOT_HEARTBEAT)
    is_alive = False
    if hb:
        try:
            is_alive = (int(time.time() * 1000) - int(hb)) <= heartbeat_alive_sec * 1000
        except (ValueError, TypeError):
            is_alive = False
    return status, is_alive
