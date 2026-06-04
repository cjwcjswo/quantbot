"""Daily log + calendar service (backend doc §25.8)."""

from __future__ import annotations

from typing import Any

from apps.api.repositories import daily_repository


async def daily(session_factory: Any, *, day: str, mode: str | None) -> dict:
    return await daily_repository.daily_log(session_factory, day=day, mode=mode)


async def calendar(
    session_factory: Any, *, year: int, month: int, mode: str | None
) -> dict:
    return await daily_repository.calendar(
        session_factory, year=year, month=month, mode=mode)
