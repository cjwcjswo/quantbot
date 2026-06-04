"""Order queries (backend doc §12)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from apps.api.repositories.base import apply_eq, apply_time_range, paginate, row_to_dict
from packages.storage.models import OrderRow


async def list_orders(
    session_factory: Any, *, symbol=None, status=None, source=None, mode=None,
    frm: datetime | None = None, to: datetime | None = None,
    limit: int = 50, offset: int = 0,
) -> list[dict]:
    stmt = select(OrderRow)
    stmt = apply_eq(stmt, OrderRow,
                    {"symbol": symbol, "status": status, "source": source, "mode": mode})
    stmt = apply_time_range(stmt, OrderRow, frm=frm, to=to)
    stmt = paginate(stmt.order_by(OrderRow.id.desc()), limit=limit, offset=offset)
    async with session_factory() as s:
        rows = (await s.execute(stmt)).scalars().all()
    return [row_to_dict(r) for r in rows]


async def get_by_order_id(session_factory: Any, order_id: str) -> dict | None:
    async with session_factory() as s:
        row = (await s.execute(
            select(OrderRow).where(OrderRow.order_id == order_id)
            .order_by(OrderRow.id.desc()).limit(1)
        )).scalar_one_or_none()
    return row_to_dict(row) if row else None
