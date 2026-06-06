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

    latest_equity = None
    if not data:
        latest_equity = await daily_repository.latest_daily_equity(session_factory)
        rows = await daily_repository.list_daily_pnl(session_factory, limit=1)
        if latest_equity:
            data = {
                "realized": latest_equity.get("realized", "0"),
                "unrealized": latest_equity.get("unrealized", "0"),
                "fees": latest_equity.get("fees", "0"),
                "funding_fees": latest_equity.get("funding_fees", "0"),
                "equity": latest_equity.get("current_equity"),
                "start_equity": latest_equity.get("start_equity"),
                "daily_net_pnl": latest_equity.get("net_pnl"),
                "daily_net_pnl_percent": latest_equity.get("net_pnl_percent"),
                "max_drawdown_today": latest_equity.get("max_drawdown_percent"),
                "updated_at": latest_equity.get("updated_at"),
            }
        elif rows:
            data = {
                "realized": rows[0].get("realized", "0"),
                "unrealized": rows[0].get("unrealized", "0"),
                "fees": rows[0].get("fees", "0"),
            }
        degraded = degraded or not raw
    elif data.get("start_equity") is None or "daily_net_pnl" not in data:
        latest_equity = await daily_repository.latest_daily_equity(session_factory)
        if latest_equity:
            data.setdefault("start_equity", latest_equity.get("start_equity"))
            data.setdefault("max_drawdown_today", latest_equity.get("max_drawdown_percent"))
            data.setdefault("updated_at", latest_equity.get("updated_at"))
            if "daily_net_pnl" not in data:
                start = _num(data.get("start_equity"))
                equity = _num(data.get("equity"))
                if start > 0 and equity > 0:
                    net = equity - start
                    data["daily_net_pnl"] = f"{net:.2f}"
                    data.setdefault("daily_net_pnl_percent", f"{net / start * 100:.2f}")
                else:
                    data["daily_net_pnl"] = latest_equity.get("net_pnl")
                    data.setdefault(
                        "daily_net_pnl_percent",
                        latest_equity.get("net_pnl_percent"),
                    )

    realized = _num(data.get("realized"))
    unrealized = _num(data.get("unrealized"))
    fees = _num(data.get("fees"))
    funding = _num(data.get("funding_fees"))
    daily_net = _num(data.get("daily_net_pnl"))
    if "daily_net_pnl" not in data:
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
        "start_equity": data.get("start_equity"),
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


async def monthly(session_factory: Any, *, limit: int = 24) -> list[dict]:
    return await daily_repository.monthly_pnl(session_factory, limit=limit)
