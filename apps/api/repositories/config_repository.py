"""Strategy config queries (backend doc §15)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from packages.storage.models import StrategyConfigRow


async def latest(session_factory: Any) -> StrategyConfigRow | None:
    async with session_factory() as s:
        return (await s.execute(
            select(StrategyConfigRow).order_by(StrategyConfigRow.id.desc()).limit(1)
        )).scalar_one_or_none()


async def insert_version(
    session_factory: Any, *, name: str, config: dict, version: int, mode: str | None
) -> StrategyConfigRow:
    async with session_factory() as s:
        row = StrategyConfigRow(
            name=name, enabled=True, config=config, version=version, mode=mode)
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return row
