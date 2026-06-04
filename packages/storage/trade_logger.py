"""TradeLogger: persists events and trading records to PostgreSQL (arch doc §6.23).

It doubles as an EventBus sink (``await trade_logger(event)``) writing bot_events,
plus typed helpers for signals, orders, fills, positions and protection events.
Each call uses its own short-lived session so it is safe to fan out concurrently.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.core.events import BotEvent
from packages.core.models import Fill, Order, Position, Signal
from packages.storage.models import (
    BotEventRow,
    CommandLogRow,
    DailyPnlRow,
    FillRow,
    ManualInterventionLogRow,
    OrderRow,
    PaperAccountSnapshotRow,
    PositionRow,
    PositionProtectionLogRow,
    ReconciliationLogRow,
    SignalRow,
    TradeRow,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TradeLogger:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory

    async def _add(self, row) -> None:
        async with self._sf() as session:
            session.add(row)
            await session.commit()

    # EventBus sink
    async def __call__(self, event: BotEvent) -> None:
        await self._add(
            BotEventRow(
                type=event.type.value,
                symbol=event.symbol,
                message=event.message,
                data=event.data,
            )
        )

    async def log_signal(self, signal: Signal, *, entry_mode: str | None = None) -> None:
        await self._add(
            SignalRow(
                symbol=signal.symbol,
                direction=signal.direction.value,
                strategy=signal.strategy,
                score=str(signal.score),
                reason=signal.reason,
                entry_mode=entry_mode,
            )
        )

    async def log_order(
        self,
        order: Order,
        *,
        mode: str | None = None,
        source: str | None = None,
    ) -> None:
        await self._add(
            OrderRow(
                symbol=order.symbol,
                side=order.side.value,
                order_type=order.order_type.value,
                qty=str(order.qty),
                price=str(order.price) if order.price is not None else None,
                status=order.status.value,
                client_order_id=order.client_order_id,
                order_id=order.order_id,
                reduce_only=order.reduce_only,
                entry_mode=order.entry_mode.value if order.entry_mode else None,
                source=source or getattr(order.source, "value", None),
                mode=mode,
                filled_qty=str(order.filled_qty)
                if getattr(order, "filled_qty", None) is not None
                else None,
                avg_fill_price=str(order.avg_fill_price)
                if getattr(order, "avg_fill_price", None) is not None
                else None,
                created_at=getattr(order, "created_at", None),
                updated_at=_utcnow(),
            )
        )

    async def log_fill(
        self,
        fill: Fill,
        realized_pnl: str = "0",
        *,
        mode: str | None = None,
        slippage: str | None = None,
    ) -> None:
        await self._add(
            FillRow(
                symbol=fill.symbol,
                order_id=fill.order_id,
                side=fill.side.value,
                price=str(fill.price),
                qty=str(fill.qty),
                fee=str(fill.fee),
                realized_pnl=realized_pnl,
                mode=mode,
                slippage=slippage,
            )
        )

    async def log_position(
        self,
        position: Position,
        *,
        mode: str | None = None,
        strategy_id: str | None = None,
        mark_price: str | None = None,
        protection_status: str | None = None,
    ) -> None:
        await self._add(
            PositionRow(
                symbol=position.symbol,
                side=position.side.value,
                status=position.status.value,
                source=position.source.value,
                qty=str(position.qty),
                avg_entry_price=str(position.avg_entry_price),
                manual_added_qty=str(position.manual_added_qty),
                stop_loss_price=str(position.stop_loss_price)
                if position.stop_loss_price is not None
                else None,
                take_profit_price=str(position.take_profit_price)
                if position.take_profit_price is not None
                else None,
                entry_mode=position.entry_mode.value if position.entry_mode else None,
                realized_pnl=str(position.realized_pnl),
                exit_reason=position.exit_reason.value if position.exit_reason else None,
                closed_at=position.closed_at,
                mode=mode,
                leverage=str(position.leverage),
                mark_price=mark_price,
                unrealized_pnl=str(position.unrealized_pnl),
                strategy_id=strategy_id or (position.strategy_reason or None),
                protection_status=protection_status,
                opened_at=position.opened_at,
            )
        )

    async def log_trade(
        self,
        *,
        symbol: str,
        side: str,
        qty: str,
        entry_price: str,
        exit_price: str,
        realized_pnl: str,
        exit_reason: str | None,
        trade_id: str | None = None,
        strategy_id: str | None = None,
        entry_mode: str | None = None,
        mode: str | None = None,
        leverage: str | None = None,
        fees: str = "0",
        funding_fees: str = "0",
        gross_pnl: str | None = None,
        net_pnl: str | None = None,
        r_multiple: str | None = None,
        opened_at: datetime | None = None,
        closed_at: datetime | None = None,
    ) -> None:
        await self._add(
            TradeRow(
                trade_id=trade_id or uuid.uuid4().hex,
                symbol=symbol, side=side, qty=qty, entry_price=entry_price,
                exit_price=exit_price, realized_pnl=realized_pnl, exit_reason=exit_reason,
                strategy_id=strategy_id, entry_mode=entry_mode, mode=mode,
                leverage=leverage, fees=fees, funding_fees=funding_fees,
                gross_pnl=gross_pnl, net_pnl=net_pnl, r_multiple=r_multiple,
                opened_at=opened_at, closed_at=closed_at,
            )
        )

    async def log_command(
        self, *, command_id: str, type: str, payload: dict, result: str = "received"
    ) -> None:
        await self._add(
            CommandLogRow(command_id=command_id, type=type, payload=payload, result=result)
        )

    async def log_protection(
        self, symbol: str, event: str, *, tp=None, sl=None, success: bool = True
    ) -> None:
        await self._add(
            PositionProtectionLogRow(
                symbol=symbol, event=event,
                take_profit=str(tp) if tp is not None else None,
                stop_loss=str(sl) if sl is not None else None,
                success=success,
            )
        )

    async def log_reconciliation(self, summary: dict) -> None:
        await self._add(ReconciliationLogRow(summary=summary))

    async def log_manual_intervention(
        self, symbol: str, kind: str, data: dict
    ) -> None:
        await self._add(
            ManualInterventionLogRow(symbol=symbol, kind=kind, data=data)
        )

    async def log_paper_snapshot(
        self, *, equity: str, balance: str, unrealized_pnl: str = "0"
    ) -> None:
        await self._add(
            PaperAccountSnapshotRow(
                equity=equity, balance=balance, unrealized_pnl=unrealized_pnl
            )
        )

    async def log_daily_pnl(
        self, *, day: str, realized: str, unrealized: str, fees: str, net: str
    ) -> None:
        """Upsert the latest PnL snapshot for ``day`` (impl doc §18)."""
        async with self._sf() as session:
            row = (
                await session.execute(
                    select(DailyPnlRow).where(DailyPnlRow.day == day)
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    DailyPnlRow(day=day, realized=realized, unrealized=unrealized,
                                fees=fees, net=net)
                )
            else:
                row.realized, row.unrealized = realized, unrealized
                row.fees, row.net = fees, net
            await session.commit()
