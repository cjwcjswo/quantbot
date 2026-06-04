"""Fixtures for the Backend API tests (reuses tests/conftest.py: config, redis, session_factory)."""

from __future__ import annotations

import time
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from apps.api.config import ApiSettings
from apps.api.main import create_app


@pytest.fixture
def api_settings() -> ApiSettings:
    return ApiSettings(api_run_maintenance=False, api_auth_enabled=False)


@pytest.fixture
def app(session_factory, redis, config, api_settings):
    return create_app(
        session_factory=session_factory, redis=redis, config=config,
        api_settings=api_settings, start_stream=False,
    )


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def add_rows(session_factory, *rows: Any) -> None:
    async with session_factory() as s:
        for r in rows:
            s.add(r)
        await s.commit()


async def set_alive(redis, state: str = "RUNNING", mode: str = "PAPER") -> None:
    await redis.set("bot:status", state)
    await redis.set("bot:mode", mode)
    await redis.set("bot:heartbeat", str(int(time.time() * 1000)))


async def set_stale(redis, state: str = "RUNNING", mode: str = "PAPER") -> None:
    await redis.set("bot:status", state)
    await redis.set("bot:mode", mode)
    await redis.set("bot:heartbeat", str(int(time.time() * 1000) - 60_000))
