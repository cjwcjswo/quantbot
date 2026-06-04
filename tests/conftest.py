"""Shared pytest fixtures."""

from __future__ import annotations

import fakeredis
import fakeredis.aioredis
import pytest
import pytest_asyncio

from packages.config import load_app_config
from packages.storage.database import (
    init_models,
    make_memory_engine,
    make_session_factory,
)


@pytest.fixture
def config():
    return load_app_config("config/quantbot.yaml")


@pytest.fixture
def redis():
    """A standalone fake Redis client (async)."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def redis_server():
    """A FakeServer so multiple clients can share the same backing store
    (used to simulate two processes contending for the runtime lock)."""
    return fakeredis.FakeServer()


class EventCollector:
    """Async event sink that records every published BotEvent."""

    def __init__(self) -> None:
        self.events = []

    async def __call__(self, event) -> None:
        self.events.append(event)

    def types(self):
        return [e.type for e in self.events]

    def of_type(self, event_type):
        return [e for e in self.events if e.type == event_type]


@pytest.fixture
def events():
    return EventCollector()


@pytest_asyncio.fixture
async def session_factory():
    """In-memory SQLite session factory with all tables created."""
    engine = make_memory_engine()
    await init_models(engine)
    yield make_session_factory(engine)
    await engine.dispose()
