"""Backend doc §23 Phase 8 / §21: failure handling."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from apps.api.config import ApiSettings
from apps.api.main import create_app


class BoomRedis:
    async def get(self, *a):
        raise RuntimeError("redis down")

    async def ping(self):
        raise RuntimeError("redis down")

    async def lpush(self, *a):
        raise RuntimeError("redis down")


def _app(session_factory, config):
    return create_app(
        session_factory=session_factory, redis=BoomRedis(), config=config,
        api_settings=ApiSettings(api_run_maintenance=False), start_stream=False)


async def test_status_degraded_when_redis_down(session_factory, config):
    app = _app(session_factory, config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/bot/status")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["degraded"] is True
    assert data["state"] == "UNKNOWN"


async def test_command_503_when_redis_down(session_factory, config):
    app = _app(session_factory, config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/bot/start", json={})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "REDIS_ERROR"


async def test_health_reports_redis_down(session_factory, config):
    app = _app(session_factory, config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        data = (await c.get("/health")).json()["data"]
    assert data["redis"] == "DOWN"
    assert data["status"] == "DEGRADED"
