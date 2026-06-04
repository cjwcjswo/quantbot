"""PnL summary from Redis, with Postgres daily_pnl fallback (backend doc §14)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from apps.api.repositories import daily_repository
from packages.messaging import state_keys
from packages.storage.models import PaperAccountSnapshotRow


async def _latest_paper_snapshot(session_factory: Any) -> PaperAccountSnapshotRow | None:
    async with session_factory() as s:
        return (
            await s.execute(
                select(PaperAccountSnapshotRow)
                .order_by(PaperAccountSnapshotRow.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()


def _num(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


async def summary(redis: Any, session_factory: Any) -> dict:
    raw = None
    mode = None
    degraded = False
    try:
        raw = await redis.get(state_keys.BOT_PNL)
        mode = await redis.get(state_keys.BOT_MODE)
    except Exception:  # noqa: BLE001
        degraded = True

    data: dict = {}
    if raw:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = {}

    if not data:
        rows = await daily_repository.list_daily_pnl(session_factory, limit=1)
        if rows:
            data = {
                "realized": rows[0].get("realized", "0"),
                "unrealized": rows[0].get("unrealized", "0"),
                "fees": rows[0].get("fees", "0"),
            }
        degraded = degraded or not raw

    realized = _num(data.get("realized"))
    unrealized = _num(data.get("unrealized"))
    fees = _num(data.get("fees"))
    funding = _num(data.get("funding_fees"))
    daily_net = realized + unrealized - fees - funding

    # equity/unrealized are not in bot:pnl; in PAPER they live in the snapshot table.
    equity = data.get("equity")
    if equity is None:
        snap = await _latest_paper_snapshot(session_factory)
        if snap is not None:
            equity = snap.equity
            if not data.get("unrealized"):
                unrealized = _num(snap.unrealized_pnl)
                daily_net = realized + unrealized - fees - funding

    return {
        "mode": mode,
        "equity": equity,
        "daily_net_pnl": f"{daily_net:.2f}",
        "daily_net_pnl_percent": data.get("daily_net_pnl_percent"),
        "realized_pnl": f"{realized:.2f}",
        "unrealized_pnl": f"{unrealized:.2f}",
        "fees": f"{fees:.2f}",
        "funding_fees": f"{funding:.2f}",
        "max_drawdown_today": data.get("max_drawdown_today"),
        "updated_at": data.get("updated_at"),
        "degraded": degraded,
    }


async def daily(session_factory: Any, *, limit: int = 90) -> list[dict]:
    return await daily_repository.list_daily_pnl(session_factory, limit=limit)
