"""Position queries (backend doc §11)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
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


def _qty_is_positive(value: Any) -> bool:
    try:
        return Decimal(str(value)) > 0
    except (InvalidOperation, TypeError, ValueError):
        return True


async def list_open(session_factory: Any) -> list[dict]:
    async with session_factory() as s:
        rows = (await s.execute(
            select(PositionRow).order_by(PositionRow.id.desc())
        )).scalars().all()

    # PositionRow is an append-only snapshot table. A closed snapshot can exist
    # after older ACTIVE snapshots for the same symbol, so decide openness from
    # the latest row per symbol instead of filtering ACTIVE rows first.
    seen: dict[str, dict] = {}
    for r in rows:
        if r.symbol in seen:
            continue
        seen[r.symbol] = row_to_dict(r)

    out: list[dict] = []
    for r in seen.values():
        if r.get("status") in _OPEN and _qty_is_positive(r.get("qty")):
            out.append(r)
    return out


async def list_stale_open_snapshots(session_factory: Any) -> list[dict]:
    """Return historical open snapshots whose latest symbol snapshot is closed."""

    async with session_factory() as s:
        rows = (await s.execute(
            select(PositionRow).order_by(PositionRow.id.desc())
        )).scalars().all()

    latest_by_symbol: dict[str, PositionRow] = {}
    for r in rows:
        latest_by_symbol.setdefault(r.symbol, r)

    stale: list[dict] = []
    for r in rows:
        latest = latest_by_symbol.get(r.symbol)
        if (
            latest is not None
            and latest.id != r.id
            and latest.status == "CLOSED"
            and r.status in _OPEN
        ):
            stale.append(row_to_dict(r))
    return stale


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
