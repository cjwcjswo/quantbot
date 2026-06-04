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
from packages.core.enums import PositionSource, PositionStatus
from packages.core.events import BotEvent, BotEventType
from packages.exchange import ExchangeGateway
from packages.messaging import EventBus
from packages.reconciliation.manual_intervention_handler import (
    ManualInterventionHandler,
)

logger = logging.getLogger(__name__)


@dataclass
class ReconcileResult:
    external_positions: list[str] = field(default_factory=list)
    qty_mismatches: list[str] = field(default_factory=list)
    external_closes: list[str] = field(default_factory=list)
    external_orders: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(
            self.external_positions
            or self.qty_mismatches
            or self.external_closes
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
                await self._handler.handle_external_position(exch)
                result.external_positions.append(symbol)
            elif internal.source == PositionSource.EXTERNAL:
                # Keep adopted external position in sync (still not managed).
                internal.qty = exch.size
                internal.avg_entry_price = exch.avg_price
                internal.liq_price = exch.liq_price
            elif internal.qty != exch.size:
                await self._handler.handle_qty_mismatch(internal, exch)
                result.qty_mismatches.append(symbol)
            else:
                # In sync: refresh live fields from the source of truth.
                internal.liq_price = exch.liq_price
                internal.unrealized_pnl = exch.unrealized_pnl

        # Internal positions Bybit no longer reports => closed externally.
        for symbol, internal in list(self._state.positions.items()):
            if (
                internal.source == PositionSource.BOT
                and internal.status in (PositionStatus.ACTIVE, PositionStatus.PENDING)
                and symbol not in exch_by_symbol
            ):
                await self._handler.handle_external_close(internal)
                result.external_closes.append(symbol)

    async def _reconcile_orders(self, result: ReconcileResult) -> None:
        known = self._state.known_order_ids()
        for order in await self._gw.get_open_orders():
            if order.order_id in known or (
                order.client_order_id and order.client_order_id in known
            ):
                continue
            await self._handler.handle_external_order(order)
            result.external_orders.append(order.order_id)

    def next_interval_sec(self) -> int:
        """Cadence for the reconciliation loop (impl doc §4.2)."""
        if self._after_order_event:
            self._after_order_event = False
            return self._cfg.interval_sec_after_order_event
        if self._state.has_open_bot_position():
            return self._cfg.interval_sec_when_position_open
        return self._cfg.interval_sec_when_flat
