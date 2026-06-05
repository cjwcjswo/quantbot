"""Position list/detail: Redis snapshot first, Postgres fallback (backend doc §11)."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.api.repositories import position_repository
from packages.messaging import state_keys

_FIELDS = (
    "symbol", "side", "source", "mode", "qty", "manual_added_qty",
    "avg_entry_price", "mark_price", "unrealized_pnl", "leverage",
    "entry_mode", "strategy_id", "protection_status", "opened_at",
)

_OPEN_STATUSES = {"PENDING", "ACTIVE", "CLOSING"}


def _qty_is_positive(value: Any) -> bool:
    if value is None:
        return True
    try:
        return Decimal(str(value)) > 0
    except (InvalidOperation, ValueError):
        return True


def _is_open_snapshot(p: dict) -> bool:
    status = p.get("status")
    if status is not None and status not in _OPEN_STATUSES:
        return False
    return _qty_is_positive(p.get("qty"))


def _from_snapshot(p: dict, mode: str | None) -> dict:
    manual = p.get("manual_added_qty", "0")
    source = p.get("source", "BOT")
    if source == "BOT" and manual not in (None, "0", "0.0"):
        source = "MANUAL_ADDED"
    return {
        "symbol": p.get("symbol"),
        "side": p.get("side"),
        "source": source,
        "mode": p.get("mode") or mode,
        "qty": p.get("qty"),
        "manual_added_qty": manual,
        "avg_entry_price": p.get("avg_entry_price"),
        "mark_price": p.get("mark_price"),
        "unrealized_pnl": p.get("unrealized_pnl"),
        "unrealized_pnl_percent": p.get("unrealized_pnl_percent"),
        "leverage": p.get("leverage"),
        "entry_mode": p.get("entry_mode"),
        "strategy_id": p.get("strategy_id"),
        "protection_status": p.get("protection_status", "UNKNOWN"),
        "stop_loss_price": p.get("stop_loss"),
        "take_profit_price": p.get("take_profit"),
        "opened_at": p.get("opened_at"),
    }


def _from_row(r: dict) -> dict:
    manual = r.get("manual_added_qty", "0")
    source = r.get("source", "BOT")
    if source == "BOT" and manual not in (None, "0", "0.0"):
        source = "MANUAL_ADDED"
    return {
        "symbol": r.get("symbol"),
        "side": r.get("side"),
        "source": source,
        "mode": r.get("mode"),
        "qty": r.get("qty"),
        "manual_added_qty": manual,
        "avg_entry_price": r.get("avg_entry_price"),
        "mark_price": r.get("mark_price"),
        "unrealized_pnl": r.get("unrealized_pnl"),
        "leverage": r.get("leverage"),
        "entry_mode": r.get("entry_mode"),
        "strategy_id": r.get("strategy_id"),
        "protection_status": r.get("protection_status", "UNKNOWN"),
        "stop_loss_price": r.get("stop_loss_price"),
        "take_profit_price": r.get("take_profit_price"),
        "opened_at": r.get("opened_at"),
    }


async def list_positions(redis: Any, session_factory: Any) -> dict:
    degraded = False
    raw = None
    mode = None
    try:
        raw = await redis.get(state_keys.BOT_POSITIONS)
        mode = await redis.get(state_keys.BOT_MODE)
    except Exception:  # noqa: BLE001
        degraded = True

    if raw:
        try:
            data = json.loads(raw)
            open_data = [p for p in data if _is_open_snapshot(p)]
            return {"positions": [_from_snapshot(p, mode) for p in open_data],
                    "source": "redis"}
        except (ValueError, TypeError):
            degraded = True  # malformed snapshot -> fall through to DB

    rows = await position_repository.list_open(session_factory)
    return {"positions": [_from_row(r) for r in rows],
            "source": "postgres", "degraded": degraded}


async def detail(session_factory: Any, symbol: str) -> dict | None:
    return await position_repository.detail(session_factory, symbol)


async def exists(redis: Any, session_factory: Any, symbol: str) -> bool:
    listing = await list_positions(redis, session_factory)
    return any(p["symbol"] == symbol for p in listing["positions"])
