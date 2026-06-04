"""Bot event queries (backend doc §16). Severity derived if not stored."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from apps.api.repositories.base import apply_time_range, paginate, row_to_dict
from packages.storage.models import BotEventRow

_CRITICAL = {"EMERGENCY_STOP", "EMERGENCY_CLOSE", "EMERGENCY_TPSL_FAILED"}
_ERROR = {"TPSL_FAILED", "ORDER_FAILED", "KILL_SWITCH_TRIPPED",
          "RISK_LOCKED", "ORDER_LOCKED"}
_WARNING = {"DATA_QUALITY_BLOCK", "NEW_ENTRIES_PAUSED",
            "EXTERNAL_POSITION_DETECTED", "EXTERNAL_ORDER_DETECTED",
            "POSITION_QUANTITY_MISMATCH"}


def derive_severity(event_type: str, stored: str | None) -> str:
    if stored and stored != "INFO":
        return stored
    if event_type in _CRITICAL:
        return "CRITICAL"
    if event_type in _ERROR:
        return "ERROR"
    if event_type in _WARNING:
        return "WARNING"
    return stored or "INFO"


async def list_events(
    session_factory: Any, *, event_type=None, severity=None, symbol=None,
    frm: datetime | None = None, to: datetime | None = None,
    limit: int = 50, offset: int = 0,
) -> list[dict]:
    stmt = select(BotEventRow)
    if event_type is not None:
        stmt = stmt.where(BotEventRow.type == event_type)
    if symbol is not None:
        stmt = stmt.where(BotEventRow.symbol == symbol)
    stmt = apply_time_range(stmt, BotEventRow, frm=frm, to=to)
    stmt = paginate(stmt.order_by(BotEventRow.id.desc()), limit=limit, offset=offset)
    async with session_factory() as s:
        rows = (await s.execute(stmt)).scalars().all()
    out = []
    for r in rows:
        d = row_to_dict(r)
        d["severity"] = derive_severity(r.type, r.severity)
        out.append(d)
    if severity is not None:
        out = [d for d in out if d["severity"] == severity]
    return out


async def latest(session_factory: Any) -> dict | None:
    async with session_factory() as s:
        row = (await s.execute(
            select(BotEventRow).order_by(BotEventRow.id.desc()).limit(1)
        )).scalar_one_or_none()
    if row is None:
        return None
    d = row_to_dict(row)
    d["severity"] = derive_severity(row.type, row.severity)
    return d
