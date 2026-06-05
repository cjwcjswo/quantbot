"""Bot event queries (backend doc §16). Severity derived if not stored."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select

from apps.api.repositories.base import apply_time_range, paginate, row_to_dict
from packages.core.events import (
    event_severity,
    event_types_for_severity,
    non_info_event_types,
)
from packages.storage.models import BotEventRow


def derive_severity(event_type: str, stored: str | None) -> str:
    return event_severity(event_type, stored)


def apply_severity_filter(stmt, severity: str | None):
    if severity is None:
        return stmt
    value = severity.upper()
    if value == "INFO":
        return stmt.where(
            or_(BotEventRow.severity == "INFO", BotEventRow.severity.is_(None)),
            BotEventRow.type.notin_(non_info_event_types()),
        )
    event_types = event_types_for_severity(value)
    if not event_types:
        return stmt.where(BotEventRow.severity == value)
    return stmt.where(
        or_(
            BotEventRow.severity == value,
            and_(
                or_(BotEventRow.severity == "INFO", BotEventRow.severity.is_(None)),
                BotEventRow.type.in_(event_types),
            ),
        )
    )


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
    stmt = apply_severity_filter(stmt, severity)
    stmt = apply_time_range(stmt, BotEventRow, frm=frm, to=to)
    stmt = paginate(stmt.order_by(BotEventRow.id.desc()), limit=limit, offset=offset)
    async with session_factory() as s:
        rows = (await s.execute(stmt)).scalars().all()
    out = []
    for r in rows:
        d = row_to_dict(r)
        d["severity"] = derive_severity(r.type, r.severity)
        out.append(d)
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
