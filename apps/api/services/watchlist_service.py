"""Watch list: read the bot's scanner candidates + entry preview from Redis.

The Bot Engine publishes ``bot:watchlist`` (arch §6.24); the dashboard reads it
to show which symbols are being watched, their LONG/SHORT lean and how close each
is to a real entry — so a user can anticipate entries. Redis-only (no Postgres
fallback): the watch list is ephemeral realtime state.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from packages.messaging import state_keys

# Most actionable first (BREAKOUT) -> no signal last.
_READINESS_RANK = {
    "BREAKOUT": 0,
    "NEAR": 1,
    "SCOUT_ZONE": 2,
    "WATCHING": 3,
    "NO_SIGNAL": 4,
}


def _score(entry: dict) -> Decimal:
    raw = entry.get("signal_score")
    if raw in (None, ""):
        return Decimal(0)
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _sort_key(entry: dict) -> tuple[int, Decimal, str]:
    rank = _READINESS_RANK.get(str(entry.get("readiness")), 9)
    return (rank, -_score(entry), str(entry.get("symbol", "")))


async def get_watchlist(redis: Any) -> dict:
    degraded = False
    raw = mode = state = None
    try:
        raw = await redis.get(state_keys.BOT_WATCHLIST)
        mode = await redis.get(state_keys.BOT_MODE)
        state = await redis.get(state_keys.BOT_STATUS)
    except Exception:  # noqa: BLE001 - Redis down => degraded (§21.1)
        degraded = True

    entries: list[dict] = []
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                entries = [e for e in data if isinstance(e, dict)]
            else:
                degraded = True
        except (ValueError, TypeError):
            degraded = True  # malformed snapshot

    entries.sort(key=_sort_key)
    return {
        "watchlist": entries,
        "count": len(entries),
        "mode": mode,
        "bot_state": state or "UNKNOWN",
        "source": "redis",
        "degraded": degraded,
    }
