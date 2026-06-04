"""Async SQLAlchemy engine / session helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from packages.storage.models import Base


def create_engine(url: str, **kwargs: Any) -> AsyncEngine:
    """Create an async engine. For PostgreSQL pass ``postgresql+asyncpg://...``."""
    return create_async_engine(url, **kwargs)


def make_memory_engine() -> AsyncEngine:
    """In-memory SQLite engine shared across sessions (tests)."""
    from sqlalchemy.pool import StaticPool

    return create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


async def init_models(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
