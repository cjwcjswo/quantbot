"""Trade queries + trade detail assembly (backend doc §13, §25.9)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Numeric, cast, func, or_, select

from apps.api.repositories.base import apply_eq, apply_time_range, paginate, row_to_dict
from packages.storage.models import (
    BotEventRow,
    FillRow,
    ManualInterventionLogRow,
    OrderRow,
    PositionProtectionLogRow,
    TradeRow,
)

# event types surfaced in a trade timeline (§25.9)
_TIMELINE_TYPES = (
    "SIGNAL", "SIGNAL_CREATED", "ORDER_PLACED", "ORDER_CREATED", "ORDER_FILLED",
    "POSITION_OPENED", "TPSL_SET", "TPSL_VERIFIED", "MANUAL_ADD_DETECTED",
    "MANUAL_QTY_INCREASED", "PARTIAL_TAKE_PROFIT", "TRAILING_UPDATED",
    "SCENARIO_INVALID", "SCOUT_PENDING_STARTED", "SCOUT_CONFIRMED",
    "SCOUT_WARNING_STARTED", "SCOUT_WARNING_RECOVERED", "SCOUT_ACTIVATED",
    "SCOUT_DEFENSIVE_REDUCE", "SCOUT_CATASTROPHIC_REDUCE",
    "SCOUT_INVALIDATED", "SCENARIO_INVALID_REDUCE", "STAGNATION_REDUCE",
    "STAGNATION_DELAYED_BY_ENTRY_MODE", "RUNNER_MODE_ACTIVATED",
    "RUNNER_TREND_STRENGTH_CHANGED", "RUNNER_TRAILING_UPDATED",
    "RUNNER_EXCHANGE_SL_UPDATED", "RUNNER_EXCHANGE_SL_UPDATE_FAILED",
    "RUNNER_TRAILING_STOP", "RUNNER_SCENARIO_INVALID", "RUNNER_POST_EXIT_MFE",
    "EMERGENCY_CLOSE", "POSITION_CLOSED",
)


async def list_trades(
    session_factory: Any, *, symbol=None, strategy_id=None, entry_mode=None, mode=None,
    exit_reason=None, pnl=None,
    frm: datetime | None = None, to: datetime | None = None,
    limit: int = 50, offset: int = 0,
) -> list[dict]:
    stmt = select(TradeRow)
    stmt = apply_eq(stmt, TradeRow, {
        "symbol": symbol, "strategy_id": strategy_id, "entry_mode": entry_mode,
        "mode": mode, "exit_reason": exit_reason})
    if pnl in ("positive", "negative"):
        pnl_value = cast(func.coalesce(TradeRow.net_pnl, TradeRow.realized_pnl), Numeric)
        stmt = stmt.where(pnl_value > 0 if pnl == "positive" else pnl_value < 0)
    stmt = apply_time_range(stmt, TradeRow, frm=frm, to=to)
    stmt = paginate(stmt.order_by(TradeRow.id.desc()), limit=limit, offset=offset)
    async with session_factory() as s:
        rows = (await s.execute(stmt)).scalars().all()
    return [row_to_dict(r) for r in rows]


async def detail(session_factory: Any, trade_id: str) -> dict | None:
    async with session_factory() as s:
        trade = (await s.execute(
            select(TradeRow).where(TradeRow.trade_id == trade_id).limit(1)
        )).scalar_one_or_none()
        if trade is None:
            return None
        symbol = trade.symbol
        orders = (await s.execute(
            select(OrderRow).where(OrderRow.symbol == symbol)
            .order_by(OrderRow.id))).scalars().all()
        fills = (await s.execute(
            select(FillRow).where(FillRow.symbol == symbol)
            .order_by(FillRow.id))).scalars().all()
        events = (await s.execute(
            select(BotEventRow).where(BotEventRow.symbol == symbol)
            .order_by(BotEventRow.id))).scalars().all()
        manual = (await s.execute(
            select(ManualInterventionLogRow)
            .where(ManualInterventionLogRow.symbol == symbol)
            .order_by(ManualInterventionLogRow.id))).scalars().all()
        protection = (await s.execute(
            select(PositionProtectionLogRow)
            .where(PositionProtectionLogRow.symbol == symbol)
            .order_by(PositionProtectionLogRow.id))).scalars().all()
        risk = (await s.execute(
            select(BotEventRow).where(
                BotEventRow.symbol == symbol,
                or_(BotEventRow.type.like("RISK%"),
                    BotEventRow.type.like("KILL%")))
            .order_by(BotEventRow.id))).scalars().all()

    timeline = sorted(
        [{"type": e.type, "ts": e.ts.isoformat() if e.ts else None,
          "severity": e.severity, "message": e.message, "data": e.data or {}}
         for e in events if e.type in _TIMELINE_TYPES],
        key=lambda x: x["ts"] or "",
    )
    return {
        "trade": row_to_dict(trade),
        "orders": [row_to_dict(r) for r in orders],
        "fills": [row_to_dict(r) for r in fills],
        "events": [row_to_dict(r) for r in events],
        "manual_interventions": [row_to_dict(r) for r in manual],
        "protection_events": [row_to_dict(r) for r in protection],
        "risk_events": [row_to_dict(r) for r in risk],
        "timeline": timeline,
    }
