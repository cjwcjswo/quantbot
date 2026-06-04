"""Manual intervention handling (impl doc §4.3, §4.4, arch doc §6.8).

Manual orders/positions made on the Bybit app are *emergency interventions*.
Policy:
  * Adopt external positions for display (source=EXTERNAL) but do NOT auto-manage.
  * Reflect Bybit's real qty/avgPrice into internal bot positions as the source
    of truth, recording the manual delta in ``manual_added_qty`` WITHOUT treating
    it as a new signal (entry_mode/score/reason are preserved).
  * Pause new entries for ``pause_seconds_after_external_change``.
  * Never auto-cancel external open orders.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from decimal import Decimal

from packages.config.settings import ManualInterventionSection
from packages.core.enums import PositionSource, PositionStatus
from packages.core.events import BotEvent, BotEventType
from packages.core.models import ExchangeOrder, ExchangePosition, Position
from packages.messaging import EventBus

logger = logging.getLogger(__name__)

# Optional hooks wired in later phases (None in Phase 3).
ProtectionResync = Callable[[Position], Awaitable[None]]
RiskExceededCheck = Callable[[Position], bool]


class ManualInterventionHandler:
    def __init__(
        self,
        state,  # apps.bot.runtime.RuntimeState (avoid import cycle)
        event_bus: EventBus,
        config: ManualInterventionSection,
        *,
        protection_resync: ProtectionResync | None = None,
        risk_exceeded_check: RiskExceededCheck | None = None,
        trade_logger=None,
    ) -> None:
        self._state = state
        self._events = event_bus
        self._cfg = config
        self._protection_resync = protection_resync
        self._risk_exceeded_check = risk_exceeded_check
        self._logger = trade_logger

    async def _log(self, symbol: str, kind: str, data: dict) -> None:
        if self._logger is not None:
            await self._logger.log_manual_intervention(symbol, kind, data)

    def _pause(self) -> None:
        if self._cfg.pause_new_entries_on_external_change:
            self._state.pause_new_entries(self._cfg.pause_seconds_after_external_change)

    async def handle_external_position(self, exch: ExchangePosition) -> None:
        """Bybit has a position the bot did not open (impl doc §4.4 first case)."""
        if not self._cfg.adopt_external_positions:
            self._pause()
            return
        position = Position(
            symbol=exch.symbol,
            side=exch.side,  # type: ignore[arg-type]
            status=PositionStatus.ACTIVE,
            source=PositionSource.EXTERNAL,
            qty=exch.size,
            avg_entry_price=exch.avg_price,
            leverage=exch.leverage,
            stop_loss_price=exch.stop_loss,
            take_profit_price=exch.take_profit,
            liq_price=exch.liq_price,
            strategy_reason="external (manual)",
        )
        self._state.positions[exch.symbol] = position
        self._pause()
        data = {"size": str(exch.size), "avg_price": str(exch.avg_price)}
        await self._events.publish(
            BotEvent(
                type=BotEventType.EXTERNAL_POSITION_DETECTED,
                symbol=exch.symbol,
                message="Adopted external position (not auto-managed)",
                data=data,
            )
        )
        await self._log(exch.symbol, "external_position", data)

    async def handle_external_order(self, exch: ExchangeOrder) -> None:
        """Bybit has an open order the bot did not place (impl doc §4.4 last case)."""
        self._state.external_orders[exch.order_id] = exch
        self._pause()
        data = {"order_id": exch.order_id, "qty": str(exch.qty)}
        await self._events.publish(
            BotEvent(
                type=BotEventType.EXTERNAL_ORDER_DETECTED,
                symbol=exch.symbol,
                message="External open order detected (not cancelled)",
                data=data,
            )
        )
        await self._log(exch.symbol, "external_order", data)

    async def handle_qty_mismatch(
        self, internal: Position, exch: ExchangePosition
    ) -> None:
        """Bot position qty changed on Bybit (impl doc §4.4 second case + §4.4 add)."""
        delta = exch.size - internal.qty

        if delta > 0:
            # Manual add: reflect real qty, record the delta, preserve signal fields.
            internal.manual_added_qty += delta
            event_type = BotEventType.MANUAL_ADD_DETECTED
            message = "Manual add detected; reflecting Bybit qty"
        elif delta < 0:
            event_type = BotEventType.MANUAL_PARTIAL_CLOSE_DETECTED
            message = "Manual partial close detected; reflecting Bybit qty"
        else:
            event_type = BotEventType.POSITION_QUANTITY_MISMATCH
            message = "Position qty mismatch (no delta)"

        prev_qty = internal.qty
        internal.qty = exch.size  # Bybit = source of truth
        internal.avg_entry_price = exch.avg_price  # boost avg to Bybit avgPrice
        if exch.liq_price is not None:
            internal.liq_price = exch.liq_price

        self._pause()

        await self._events.publish(
            BotEvent(
                type=BotEventType.POSITION_QUANTITY_MISMATCH,
                symbol=internal.symbol,
                message=message,
                data={
                    "prev_qty": str(prev_qty),
                    "new_qty": str(exch.size),
                    "delta": str(delta),
                    "manual_added_qty": str(internal.manual_added_qty),
                },
            )
        )
        if event_type != BotEventType.POSITION_QUANTITY_MISMATCH:
            await self._events.publish(
                BotEvent(type=event_type, symbol=internal.symbol, message=message)
            )
        await self._log(
            internal.symbol, "qty_mismatch",
            {"prev_qty": str(prev_qty), "new_qty": str(exch.size),
             "delta": str(delta), "manual_added_qty": str(internal.manual_added_qty)},
        )

        # Re-verify TP/SL covers the full position (impl doc §4.4 step 8-10).
        if internal.is_bot_managed and self._protection_resync is not None:
            resynced = await self._protection_resync(internal)
            if resynced is False:  # resync failed -> §4.4 step 10
                await self._events.publish(
                    BotEvent(
                        type=BotEventType.EMERGENCY_TPSL_FAILED,
                        symbol=internal.symbol,
                        message="TP/SL resync failed after manual qty change",
                    )
                )

        # Manual add may breach per-trade / per-symbol risk (impl doc §4.4 note).
        if (
            delta > 0
            and internal.is_bot_managed
            and self._risk_exceeded_check is not None
            and self._risk_exceeded_check(internal)
        ):
            await self._events.publish(
                BotEvent(
                    type=BotEventType.RISK_LIMIT_EXCEEDED_BY_MANUAL_INTERVENTION,
                    symbol=internal.symbol,
                    message="Manual add exceeded risk limits; pausing new entries",
                )
            )

    async def handle_external_close(self, internal: Position) -> None:
        """Internal position exists but Bybit shows flat (closed externally)."""
        internal.status = PositionStatus.CLOSED
        internal.qty = Decimal("0")
        self._pause()
        await self._events.publish(
            BotEvent(
                type=BotEventType.POSITION_CLOSED_EXTERNALLY,
                symbol=internal.symbol,
                message="Position closed outside the bot",
            )
        )
        await self._log(internal.symbol, "external_close", {})
