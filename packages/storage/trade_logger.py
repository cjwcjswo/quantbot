"""TradeLogger: persists events and trading records to PostgreSQL (arch doc §6.23).

It doubles as an EventBus sink (``await trade_logger(event)``) writing bot_events,
plus typed helpers for signals, orders, fills, positions and protection events.
Each call uses its own short-lived session so it is safe to fan out concurrently.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.core.enums import PositionStatus
from packages.core.events import BotEvent, event_severity, should_persist_event
from packages.core.models import Fill, Order, Position, Signal
from packages.storage.models import (
    BotEventRow,
    CommandLogRow,
    DailyAccountEquityRow,
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


def _max_text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    logger.warning("truncating persisted text field to %s chars", limit)
    return value[:limit]


class TradeLogger:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory

    async def _add(self, row) -> None:
        async with self._sf() as session:
            session.add(row)
            await session.commit()

    # EventBus sink
    async def __call__(self, event: BotEvent) -> None:
        severity = event_severity(event.type)
        if not should_persist_event(event.type, severity):
            return
        await self._add(
            BotEventRow(
                type=event.type.value,
                symbol=event.symbol,
                message=event.message,
                data=event.data,
                severity=severity,
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
        row_data = {
            "symbol": order.symbol,
            "side": order.side.value,
            "order_type": order.order_type.value,
            "qty": str(order.qty),
            "price": str(order.price) if order.price is not None else None,
            "status": order.status.value,
            "client_order_id": order.client_order_id,
            "order_id": order.order_id,
            "reduce_only": order.reduce_only,
            "entry_mode": order.entry_mode.value if order.entry_mode else None,
            "source": source or getattr(order.source, "value", None),
            "mode": mode,
            "filled_qty": str(order.filled_qty)
            if getattr(order, "filled_qty", None) is not None
            else None,
            "avg_fill_price": str(order.avg_fill_price)
            if getattr(order, "avg_fill_price", None) is not None
            else None,
            "created_at": getattr(order, "created_at", None),
            "updated_at": _utcnow(),
        }
        async with self._sf() as session:
            existing = await self._find_order_row(
                session,
                order_id=order.order_id,
                client_order_id=order.client_order_id,
            )
            if existing is None:
                session.add(OrderRow(**row_data))
            else:
                for key, value in row_data.items():
                    setattr(existing, key, value)
            await session.commit()

    async def update_order_status(
        self,
        *,
        order_id: str | None = None,
        client_order_id: str | None = None,
        status: str,
        filled_qty: str | None = None,
        avg_fill_price: str | None = None,
    ) -> bool:
        async with self._sf() as session:
            row = await self._find_order_row(
                session, order_id=order_id, client_order_id=client_order_id
            )
            if row is None:
                return False
            row.status = status
            if filled_qty is not None:
                row.filled_qty = filled_qty
            if avg_fill_price is not None:
                row.avg_fill_price = avg_fill_price
            row.updated_at = _utcnow()
            await session.commit()
            return True

    async def _find_order_row(
        self,
        session,
        *,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> OrderRow | None:
        filters = []
        if order_id:
            filters.append(OrderRow.order_id == order_id)
        if client_order_id:
            filters.append(OrderRow.client_order_id == client_order_id)
        if not filters:
            return None
        return (
            await session.execute(
                select(OrderRow)
                .where(or_(*filters))
                .order_by(OrderRow.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

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
        row = PositionRow(
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
            strategy_id=_max_text(strategy_id or (position.strategy_id or None), 64),
            protection_status=protection_status,
            opened_at=position.opened_at,
        )
        async with self._sf() as session:
            if position.status == PositionStatus.CLOSED:
                filters = [
                    PositionRow.symbol == position.symbol,
                    PositionRow.source == position.source.value,
                    PositionRow.status.in_(("PENDING", "ACTIVE", "CLOSING")),
                ]
                if mode is not None:
                    filters.append(PositionRow.mode == mode)
                if position.opened_at is not None:
                    filters.append(PositionRow.opened_at == position.opened_at)
                await session.execute(
                    update(PositionRow)
                    .where(*filters)
                    .values(
                        status=PositionStatus.CLOSED.value,
                        qty="0",
                        realized_pnl=str(position.realized_pnl),
                        exit_reason=position.exit_reason.value
                        if position.exit_reason
                        else None,
                        closed_at=position.closed_at,
                    )
                )
            session.add(row)
            await session.commit()

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
                strategy_id=_max_text(strategy_id, 64), entry_mode=entry_mode, mode=mode,
                leverage=leverage, fees=fees, funding_fees=funding_fees,
                gross_pnl=gross_pnl, net_pnl=net_pnl,
                r_multiple=_max_text(r_multiple, 16),
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

    async def log_account_equity(
        self,
        *,
        day: str,
        mode: str,
        equity: str,
        wallet_balance: str | None = None,
        unrealized_pnl: str = "0",
        realized_pnl: str = "0",
        fees: str = "0",
        funding_fees: str = "0",
    ) -> dict[str, str]:
        """Persist the first equity of the day as the daily PnL baseline.

        The row is keyed by ``day`` + ``mode`` in application logic so it works
        on both SQLite tests and Postgres without a migration-specific upsert.
        """
        from decimal import Decimal

        def d(value: str | None) -> Decimal:
            try:
                return Decimal(str(value)) if value is not None else Decimal(0)
            except Exception:  # noqa: BLE001
                return Decimal(0)

        def fmt(value: Decimal) -> str:
            return format(value.normalize(), "f")

        now = _utcnow()
        current = d(equity)
        wallet = fmt(d(wallet_balance)) if wallet_balance is not None else None
        async with self._sf() as session:
            row = (
                await session.execute(
                    select(DailyAccountEquityRow)
                    .where(
                        DailyAccountEquityRow.day == day,
                        DailyAccountEquityRow.mode == mode,
                    )
                    .order_by(DailyAccountEquityRow.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                row = DailyAccountEquityRow(
                    day=day,
                    mode=mode,
                    start_equity=fmt(current),
                    current_equity=fmt(current),
                    peak_equity=fmt(current),
                    wallet_balance=wallet,
                    updated_at=now,
                )
                session.add(row)

            start = d(row.start_equity)
            peak = max(d(row.peak_equity), current)
            net = current - start
            net_percent = net / start * Decimal(100) if start > 0 else Decimal(0)
            drawdown = (
                (peak - current) / peak * Decimal(100) if peak > 0 else Decimal(0)
            )
            max_drawdown = max(d(row.max_drawdown_percent), drawdown)

            row.current_equity = fmt(current)
            row.peak_equity = fmt(peak)
            row.wallet_balance = wallet
            row.unrealized_pnl = fmt(d(unrealized_pnl))
            row.realized_pnl = fmt(d(realized_pnl))
            row.fees = fmt(d(fees))
            row.funding_fees = fmt(d(funding_fees))
            row.net_pnl = fmt(net)
            row.net_pnl_percent = fmt(net_percent)
            row.max_drawdown_percent = fmt(max_drawdown)
            row.updated_at = now

            daily = (
                await session.execute(
                    select(DailyPnlRow).where(DailyPnlRow.day == day).limit(1)
                )
            ).scalar_one_or_none()
            if daily is None:
                session.add(
                    DailyPnlRow(
                        day=day,
                        realized=row.realized_pnl,
                        unrealized=row.unrealized_pnl,
                        fees=row.fees,
                        net=row.net_pnl,
                    )
                )
            else:
                daily.realized = row.realized_pnl
                daily.unrealized = row.unrealized_pnl
                daily.fees = row.fees
                daily.net = row.net_pnl

            await session.commit()
            return {
                "day": row.day,
                "mode": row.mode,
                "start_equity": row.start_equity,
                "current_equity": row.current_equity,
                "wallet_balance": row.wallet_balance or "",
                "unrealized_pnl": row.unrealized_pnl,
                "realized_pnl": row.realized_pnl,
                "fees": row.fees,
                "funding_fees": row.funding_fees,
                "net_pnl": row.net_pnl,
                "net_pnl_percent": row.net_pnl_percent,
                "max_drawdown_percent": row.max_drawdown_percent,
                "updated_at": row.updated_at.isoformat() if row.updated_at else "",
            }
