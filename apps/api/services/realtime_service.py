"""Snapshot builder for the WebSocket connect frame (backend doc §17)."""

from __future__ import annotations

from typing import Any

from apps.api.services import (
    bot_status_service,
    pnl_service,
    position_service,
    watchlist_service,
)


async def build_snapshot(redis: Any, session_factory: Any, settings: Any) -> dict:
    status = await bot_status_service.get_status(redis, session_factory, settings)
    positions = await position_service.list_positions(redis, session_factory)
    pnl = await pnl_service.summary(redis, session_factory)
    watchlist = await watchlist_service.get_watchlist(redis)
    return {
        "bot_status": status,
        "positions": positions.get("positions", []),
        "pnl": pnl,
        "watchlist": watchlist.get("watchlist", []),
    }
