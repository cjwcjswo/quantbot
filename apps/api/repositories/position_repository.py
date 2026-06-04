"""Position queries (backend doc §11)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from apps.api.repositories.base import row_to_dict
from packages.storage.models import (
    ManualInterventionLogRow,
    OrderRow,
    PositionProtectionLogRow,
    PositionRow,
    ReconciliationLogRow,
    SignalRow,
)

_OPEN = ("PENDING", "ACTIVE", "CLOSING")


async def list_open(session_factory: Any) -> list[dict]:
    async with session_factory() as s:
        rows = (await s.execute(
            select(PositionRow).where(PositionRow.status.in_(_OPEN))
            .order_by(PositionRow.id.desc())
        )).scalars().all()
    # latest row per symbol
    seen: dict[str, dict] = {}
    for r in rows:
        if r.symbol not in seen:
            seen[r.symbol] = row_to_dict(r)
    return list(seen.values())


async def latest_for_symbol(session_factory: Any, symbol: str) -> dict | None:
    async with session_factory() as s:
        row = (await s.execute(
            select(PositionRow).where(PositionRow.symbol == symbol)
            .order_by(PositionRow.id.desc()).limit(1)
        )).scalar_one_or_none()
    return row_to_dict(row) if row else None


async def detail(session_factory: Any, symbol: str) -> dict | None:
    async with session_factory() as s:
        pos = (await s.execute(
            select(PositionRow).where(PositionRow.symbol == symbol)
            .order_by(PositionRow.id.desc()).limit(1)
        )).scalar_one_or_none()
        if pos is None:
            return None
        signals = (await s.execute(
            select(SignalRow).where(SignalRow.symbol == symbol)
            .order_by(SignalRow.id.desc()).limit(20))).scalars().all()
        orders = (await s.execute(
            select(OrderRow).where(OrderRow.symbol == symbol)
            .order_by(OrderRow.id.desc()).limit(50))).scalars().all()
        protection = (await s.execute(
            select(PositionProtectionLogRow)
            .where(PositionProtectionLogRow.symbol == symbol)
            .order_by(PositionProtectionLogRow.id.desc()).limit(50))).scalars().all()
        manual = (await s.execute(
            select(ManualInterventionLogRow)
            .where(ManualInterventionLogRow.symbol == symbol)
            .order_by(ManualInterventionLogRow.id.desc()).limit(50))).scalars().all()
        recon = (await s.execute(
            select(ReconciliationLogRow)
            .order_by(ReconciliationLogRow.id.desc()).limit(10))).scalars().all()
    return {
        "position": row_to_dict(pos),
        "signals": [row_to_dict(r) for r in signals],
        "orders": [row_to_dict(r) for r in orders],
        "protection_events": [row_to_dict(r) for r in protection],
        "manual_interventions": [row_to_dict(r) for r in manual],
        "reconciliation": [row_to_dict(r) for r in recon],
    }
