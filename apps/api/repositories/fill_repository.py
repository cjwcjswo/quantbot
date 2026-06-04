"""Fill queries (backend doc §13.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from apps.api.repositories.base import apply_eq, apply_time_range, paginate, row_to_dict
from packages.storage.models import FillRow


async def list_fills(
    session_factory: Any, *, symbol=None, order_id=None, mode=None,
    frm: datetime | None = None, to: datetime | None = None,
    limit: int = 50, offset: int = 0,
) -> list[dict]:
    stmt = select(FillRow)
    stmt = apply_eq(stmt, FillRow,
                    {"symbol": symbol, "order_id": order_id, "mode": mode})
    stmt = apply_time_range(stmt, FillRow, frm=frm, to=to)
    stmt = paginate(stmt.order_by(FillRow.id.desc()), limit=limit, offset=offset)
    async with session_factory() as s:
        rows = (await s.execute(stmt)).scalars().all()
    return [row_to_dict(r) for r in rows]
