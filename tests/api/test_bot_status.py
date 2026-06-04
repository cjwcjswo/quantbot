"""Backend doc §23 Phase 2: bot status + heartbeat is_alive."""

from __future__ import annotations

from datetime import datetime

from tests.api.conftest import set_alive, set_stale


async def test_status_alive(client, redis):
    await set_alive(redis, state="RUNNING", mode="PAPER")
    r = await client.get("/bot/status")
    data = r.json()["data"]
    assert data["state"] == "RUNNING"
    assert data["mode"] == "PAPER"
    assert data["is_alive"] is True
    assert data["is_trading_enabled"] is True
    assert datetime.fromisoformat(data["heartbeat_at"]).tzinfo is not None


async def test_status_stale_heartbeat(client, redis):
    await set_stale(redis, state="RUNNING")
    data = (await client.get("/bot/status")).json()["data"]
    assert data["is_alive"] is False
    assert data["state"] == "DISCONNECTED"


async def test_status_missing_heartbeat(client):
    data = (await client.get("/bot/status")).json()["data"]
    assert data["is_alive"] is False
    assert data["state"] == "UNKNOWN"
