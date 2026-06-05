"""Backend doc §23 Phase 3: command validation, command_log -> publish, failures."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from apps.api.config import ApiSettings
from apps.api.main import create_app
from packages.storage.models import CommandLogRow
from tests.api.conftest import set_alive, set_stale


async def _queue(redis) -> list:
    return await redis.lrange("commands:bot", 0, -1)


async def _count(sf, model) -> int:
    async with sf() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


async def test_start_writes_log_then_publishes(client, redis, session_factory):
    await redis.set("bot:status", "STANDBY")
    await redis.set("bot:mode", "PAPER")
    r = await client.post("/bot/start", json={})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "PENDING"
    q = await _queue(redis)
    assert len(q) == 1
    assert '"payload":{}' in q[0]
    assert await _count(session_factory, CommandLogRow) == 1


async def test_start_live_requires_confirm(client, redis):
    await set_alive(redis, state="STANDBY", mode="LIVE")
    r = await client.post("/bot/start", json={})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_start_live_confirm_ok(client, redis):
    await set_alive(redis, state="STANDBY", mode="LIVE")
    r = await client.post("/bot/start", json={"live_confirm": True})
    assert r.status_code == 200


async def test_start_conflict_when_running(client, redis):
    await set_alive(redis, state="RUNNING")
    r = await client.post("/bot/start", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFLICT"


async def test_resume_rejected_when_risk_locked(client, redis):
    await set_alive(redis, state="RISK_LOCKED")
    r = await client.post("/bot/resume", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "BOT_COMMAND_REJECTED"


async def test_pause_rejected_when_stale(client, redis):
    await set_stale(redis, state="RUNNING")
    r = await client.post("/bot/pause", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "BOT_NOT_RUNNING"


async def test_command_stale_check_uses_configured_heartbeat(
    redis, session_factory, config
):
    await set_stale(redis, state="RUNNING")
    app = create_app(
        session_factory=session_factory,
        redis=redis,
        config=config,
        api_settings=ApiSettings(
            api_run_maintenance=False,
            heartbeat_alive_sec=120,
        ),
        start_stream=False,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/bot/pause", json={})
    assert r.status_code == 200


async def test_sync_allowed_when_stale(client, redis):
    await set_stale(redis, state="RUNNING")
    r = await client.post("/bot/sync")
    assert r.status_code == 200


async def test_command_status_lookup(client, redis):
    await redis.set("bot:status", "STANDBY")
    await redis.set("bot:mode", "PAPER")
    start = await client.post("/bot/start", json={})
    cid = start.json()["data"]["command_id"]
    r = await client.get(f"/commands/{cid}")
    assert r.status_code == 200
    assert r.json()["data"]["command_id"] == cid
    assert r.json()["data"]["result"] == "PENDING"


async def test_command_status_not_found(client):
    r = await client.get("/commands/nonexistent")
    assert r.status_code == 404


async def test_db_down_blocks_publish(redis, config):
    class BoomSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def add(self, *a):
            pass

        async def commit(self):
            raise RuntimeError("db down")

    def boom_sf():
        return BoomSession()

    await redis.set("bot:status", "STANDBY")
    await redis.set("bot:mode", "PAPER")
    app = create_app(session_factory=boom_sf, redis=redis, config=config,
                     api_settings=ApiSettings(api_run_maintenance=False),
                     start_stream=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/bot/start", json={})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "DATABASE_ERROR"
    # nothing published
    assert await redis.lrange("commands:bot", 0, -1) == []


async def test_redis_publish_failure_returns_503(app, client, redis, session_factory):
    class BoomQueue:
        async def publish(self, cmd):
            raise RuntimeError("redis down")

    await redis.set("bot:status", "STANDBY")
    await redis.set("bot:mode", "PAPER")
    app.state.command_queue = BoomQueue()
    r = await client.post("/bot/start", json={})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "COMMAND_QUEUE_UNAVAILABLE"
    # the audit log was still written before the publish attempt
    assert await _count(session_factory, CommandLogRow) == 1
