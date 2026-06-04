"""GET /watchlist: read bot:watchlist from Redis, sorted, with degrade handling."""

from __future__ import annotations

import json


async def test_watchlist_from_redis_sorted_by_readiness(client, redis):
    snap = [
        {"symbol": "AAAUSDT", "direction": "LONG", "readiness": "WATCHING",
         "signal_score": "5", "trend": "UP"},
        {"symbol": "BBBUSDT", "direction": "SHORT", "readiness": "BREAKOUT",
         "signal_score": "8", "trend": "DOWN"},
        {"symbol": "CCCUSDT", "direction": "NONE", "readiness": "NO_SIGNAL",
         "signal_score": None, "trend": "FLAT"},
        {"symbol": "DDDUSDT", "direction": "LONG", "readiness": "NEAR",
         "signal_score": "9", "trend": "UP"},
    ]
    await redis.set("bot:watchlist", json.dumps(snap))
    await redis.set("bot:status", "RUNNING")
    await redis.set("bot:mode", "PAPER")

    data = (await client.get("/watchlist")).json()["data"]
    order = [e["symbol"] for e in data["watchlist"]]
    # BREAKOUT < NEAR < WATCHING < NO_SIGNAL
    assert order == ["BBBUSDT", "DDDUSDT", "AAAUSDT", "CCCUSDT"]
    assert data["count"] == 4
    assert data["bot_state"] == "RUNNING"
    assert data["mode"] == "PAPER"
    assert data["degraded"] is False


async def test_watchlist_empty_when_absent(client, redis):
    data = (await client.get("/watchlist")).json()["data"]
    assert data["watchlist"] == []
    assert data["count"] == 0
    assert data["degraded"] is False


async def test_watchlist_malformed_degrades(client, redis):
    await redis.set("bot:watchlist", "{not json")
    data = (await client.get("/watchlist")).json()["data"]
    assert data["watchlist"] == []
    assert data["degraded"] is True
