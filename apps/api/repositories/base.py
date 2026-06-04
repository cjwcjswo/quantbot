"""Shared repository helpers: serialization, filtering, paging."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Select


def ser(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def row_to_dict(row: Any) -> dict:
    return {col.name: ser(getattr(row, col.name)) for col in row.__table__.columns}


def apply_eq(stmt: Select, model: Any, eq: dict[str, Any]) -> Select:
    for key, val in eq.items():
        if val is not None:
            stmt = stmt.where(getattr(model, key) == val)
    return stmt


def apply_time_range(
    stmt: Select, model: Any, *, frm: datetime | None, to: datetime | None,
    col: str = "ts",
) -> Select:
    column = getattr(model, col)
    if frm is not None:
        stmt = stmt.where(column >= frm)
    if to is not None:
        stmt = stmt.where(column <= to)
    return stmt


def paginate(stmt: Select, *, limit: int, offset: int) -> Select:
    return stmt.limit(max(1, min(limit, 500))).offset(max(0, offset))
