"""Bybit <-> internal state reconciliation (impl doc §4, arch doc §6.7, §10.6).

Bybit is the source of truth. Each cycle pulls real positions + open orders,
compares them with the internal registries, and routes differences to the
ManualInterventionHandler. Cycle cadence: 10s flat / 3s with a position / 1s
right after an order event (impl doc §4.2).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from packages.config.settings import ReconciliationSection
from packages.core.enums import PositionSide, PositionSource, PositionStatus, Side
from packages.core.events import BotEvent, BotEventType
from packages.core.models import ExchangeOrder
from packages.exchange import ExchangeGateway
from packages.messaging import EventBus
from packages.reconciliation.manual_intervention_handler import (
    ManualInterventionHandler,
)

logger = logging.getLogger(__name__)

_BOT_CLIENT_ORDER_PREFIXES = ("qb-", "retry-", "exit-", "ptp-")


@dataclass
class ReconcileResult:
    external_positions: list[str] = field(default_factory=list)
    qty_mismatches: list[str] = field(default_factory=list)
    external_closes: list[str] = field(default_factory=list)
    exchange_closes: list[str] = field(default_factory=list)
    external_orders: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(
            self.external_positions
            or self.qty_mismatches
            or self.external_closes
            or self.exchange_closes
            or self.external_orders
        )


class ReconciliationManager:
    def __init__(
        self,
        gateway: ExchangeGateway,
        state,  # RuntimeState
        handler: ManualInterventionHandler,
        event_bus: EventBus,
        config: ReconciliationSection,
        trade_logger=None,
    ) -> None:
        self._gw = gateway
        self._state = state
        self._handler = handler
        self._events = event_bus
        self._cfg = config
        self._logger = trade_logger
        self._after_order_event = False

    def mark_order_event(self) -> None:
        """Shorten the next cadence to 1s after an order event (impl doc §4.2)."""
        self._after_order_event = True

    async def reconcile_once(self) -> ReconcileResult:
        result = ReconcileResult()
        await self._reconcile_positions(result)
        await self._reconcile_orders(result)
        summary = {
            "external_positions": result.external_positions,
            "qty_mismatches": result.qty_mismatches,
            "external_closes": result.external_closes,
            "exchange_closes": result.exchange_closes,
            "external_orders": result.external_orders,
        }
        await self._events.publish(
            BotEvent(type=BotEventType.RECONCILED,
                     message="reconciliation cycle complete", data=summary)
        )
        if self._logger is not None:
            await self._logger.log_reconciliation(summary)
        return result

    async def _reconcile_positions(self, result: ReconcileResult) -> None:
        exch_positions = await self._gw.get_positions()
        exch_by_symbol = {p.symbol: p for p in exch_positions if p.side is not None}

        for symbol, exch in exch_by_symbol.items():
            internal = self._state.get_position(symbol)
            if internal is None or internal.status == PositionStatus.CLOSED:
                if self._state.has_bot_order_settling_for_symbol(symbol):
                    continue
                await self._handler.handle_external_position(exch)
                result.external_positions.append(symbol)
            elif internal.source == PositionSource.EXTERNAL:
                # Keep adopted external position in sync (still not managed).
                internal.qty = exch.size
                internal.avg_entry_price = exch.avg_price
                internal.liq_price = exch.liq_price
            elif internal.qty != exch.size:
                if self._state.has_bot_order_settling_for_symbol(symbol):
                    continue
                await self._handler.handle_qty_mismatch(internal, exch)
                result.qty_mismatches.append(symbol)
            else:
                # In sync: refresh live fields from the source of truth.
                internal.liq_price = exch.liq_price
                internal.unrealized_pnl = exch.unrealized_pnl

        # Internal positions Bybit no longer reports => closed externally.
        for symbol, internal in list(self._state.positions.items()):
            if (
                internal.status in (PositionStatus.ACTIVE, PositionStatus.PENDING)
                and symbol not in exch_by_symbol
            ):
                if self._state.has_bot_order_settling_for_symbol(symbol):
                    continue
                if internal.source == PositionSource.BOT:
                    await self._handler.handle_bot_exchange_close(internal)
                    result.exchange_closes.append(symbol)
                else:
                    await self._handler.handle_external_close(internal)
                    result.external_closes.append(symbol)

    async def _reconcile_orders(self, result: ReconcileResult) -> None:
        known = self._state.known_order_ids()
        for order in await self._gw.get_open_orders():
            if (
                order.order_id in known
                or (order.client_order_id and order.client_order_id in known)
                or self._is_bot_client_order(order.client_order_id)
                or self._is_bot_protection_order(order)
            ):
                continue
            await self._handler.handle_external_order(order)
            result.external_orders.append(order.order_id)

    @staticmethod
    def _is_bot_client_order(client_order_id: str | None) -> bool:
        return bool(
            client_order_id
            and client_order_id.startswith(_BOT_CLIENT_ORDER_PREFIXES)
        )

    def _is_bot_protection_order(self, order: ExchangeOrder) -> bool:
        internal = self._state.get_position(order.symbol)
        if (
            internal is None
            or internal.source != PositionSource.BOT
            or internal.status not in (PositionStatus.ACTIVE, PositionStatus.PENDING)
            or not self._is_exit_side(order.side, internal.side)
            or (order.qty > 0 and internal.qty > 0 and order.qty > internal.qty)
        ):
            return False
        return self._looks_like_exchange_trigger_order(order)

    @staticmethod
    def _is_exit_side(order_side: Side, position_side: PositionSide) -> bool:
        return (
            (position_side == PositionSide.LONG and order_side == Side.SELL)
            or (position_side == PositionSide.SHORT and order_side == Side.BUY)
        )

    @staticmethod
    def _looks_like_exchange_trigger_order(order: ExchangeOrder) -> bool:
        if order.trigger_price is not None:
            return True
        markers = " ".join(
            value.lower()
            for value in (order.stop_order_type, order.order_filter)
            if value
        )
        return any(
            token in markers
            for token in ("stop", "tpsl", "takeprofit", "take_profit", "trailing", "oco")
        )

    def next_interval_sec(self) -> int:
        """Cadence for the reconciliation loop (impl doc §4.2)."""
        if self._after_order_event:
            self._after_order_event = False
            return self._cfg.interval_sec_after_order_event
        if self._state.has_open_bot_position():
            return self._cfg.interval_sec_when_position_open
        return self._cfg.interval_sec_when_flat
