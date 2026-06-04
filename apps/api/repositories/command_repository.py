"""Command log persistence (backend doc §20)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from apps.api.repositories.base import row_to_dict
from packages.storage.models import CommandLogRow


async def write_pending(
    session_factory: Any, *, command_id: str, type: str, payload: dict
) -> None:
    """Persist a PENDING command_log. Raises on DB failure (caller must not publish)."""
    async with session_factory() as s:
        s.add(CommandLogRow(
            command_id=command_id, type=type, payload=payload, result="PENDING"))
        await s.commit()


async def get_status(session_factory: Any, command_id: str) -> dict | None:
    async with session_factory() as s:
        row = (await s.execute(
            select(CommandLogRow).where(CommandLogRow.command_id == command_id)
            .order_by(CommandLogRow.id.desc()).limit(1)
        )).scalar_one_or_none()
    return row_to_dict(row) if row else None
