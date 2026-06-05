"""Backend doc §23 Phase 4: positions list/detail/close."""

from __future__ import annotations

import json

from packages.storage.models import PositionRow
from tests.api.conftest import add_rows, set_alive


async def test_list_from_redis_snapshot(client, redis):
    snap = [
        {"symbol": "BTCUSDT", "side": "LONG", "source": "BOT", "mode": "PAPER",
         "qty": "0.01", "manual_added_qty": "0.002", "avg_entry_price": "65000",
         "protection_status": "TPSL_OK", "stop_loss": "64000", "take_profit": "67000"},
        {"symbol": "ETHUSDT", "side": "SHORT", "source": "EXTERNAL", "mode": "PAPER",
         "qty": "1", "manual_added_qty": "0", "avg_entry_price": "2000",
         "protection_status": "UNKNOWN"},
    ]
    await redis.set("bot:positions", json.dumps(snap))
    data = (await client.get("/positions")).json()["data"]
    positions = {p["symbol"]: p for p in data["positions"]}
    assert positions["BTCUSDT"]["source"] == "MANUAL_ADDED"  # manual_added_qty > 0
    assert positions["BTCUSDT"]["manual_added_qty"] == "0.002"
    assert positions["BTCUSDT"]["protection_status"] == "TPSL_OK"
    assert positions["ETHUSDT"]["source"] == "EXTERNAL"


async def test_list_filters_closed_redis_snapshot(client, redis):
    snap = [
        {"symbol": "BTCUSDT", "side": "LONG", "source": "BOT", "mode": "LIVE",
         "status": "ACTIVE", "qty": "0.01", "manual_added_qty": "0",
         "avg_entry_price": "65000"},
        {"symbol": "1000PEPEUSDT", "side": "SHORT", "source": "BOT", "mode": "LIVE",
         "status": "CLOSED", "qty": "0", "manual_added_qty": "0",
         "avg_entry_price": "0.00266"},
    ]
    await redis.set("bot:positions", json.dumps(snap))

    data = (await client.get("/positions")).json()["data"]

    assert [p["symbol"] for p in data["positions"]] == ["BTCUSDT"]


async def test_list_fallback_to_postgres(client, redis, session_factory):
    await add_rows(session_factory, PositionRow(
        symbol="BTCUSDT", side="LONG", status="ACTIVE", source="BOT",
        qty="0.01", avg_entry_price="65000", mode="PAPER", leverage="3"))
    # no redis snapshot -> postgres
    data = (await client.get("/positions")).json()["data"]
    assert data["source"] == "postgres"
    assert data["positions"][0]["symbol"] == "BTCUSDT"


async def test_list_malformed_snapshot_degrades(client, redis, session_factory):
    await redis.set("bot:positions", "{not json")
    data = (await client.get("/positions")).json()["data"]
    assert data["source"] == "postgres"
    assert data["degraded"] is True


async def test_close_publishes_command(client, redis):
    await set_alive(redis, state="RUNNING")
    await redis.set("bot:positions", json.dumps(
        [{"symbol": "BTCUSDT", "side": "LONG", "source": "BOT",
          "qty": "0.01", "manual_added_qty": "0"}]))
    r = await client.post("/positions/BTCUSDT/close", json={"close_percent": 50})
    assert r.status_code == 200
    q = await redis.lrange("commands:bot", 0, -1)
    assert "CLOSE_POSITION" in q[0]


async def test_close_invalid_percent(client, redis):
    await set_alive(redis, state="RUNNING")
    r = await client.post("/positions/BTCUSDT/close", json={"close_percent": 0})
    assert r.status_code == 422


async def test_close_rejected_when_stale(client, redis):
    from tests.api.conftest import set_stale
    await set_stale(redis, state="RUNNING")
    r = await client.post("/positions/BTCUSDT/close", json={"close_percent": 100})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "BOT_NOT_RUNNING"
