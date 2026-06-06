"""PositionProtectionManager: LIVE exchange protection verify + emergency close.

After a LIVE entry fills, the position is NOT ACTIVE until configured exchange
protection is set and verified. The current strategy requires exchange SL and
leaves exchange TP disabled so bot-managed partial TP/trailing can run.

```
verify entry-attached protection
-> missing/mismatched: set Trading Stop fallback
-> re-read configured protection (retry up to N times at interval)
-> protected => position ACTIVE
-> not protected => reduce-only MARKET emergency close
     close ok   => ORDER_LOCKED
     close fail => EMERGENCY_STOP
```
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal

from packages.config.settings import AppConfig
from packages.core.enums import PositionSide, PositionStatus, Side, TriggerBy
from packages.core.events import BotEvent, BotEventType
from packages.core.models import Position, TradingStopRequest
from packages.exchange import ExchangeGateway
from packages.execution import OrderManager
from packages.messaging import EventBus

logger = logging.getLogger(__name__)


@dataclass
class ProtectionResult:
    protected: bool
    tp: Decimal | None = None
    sl: Decimal | None = None
    reason: str = ""
    emergency: bool = False  # an emergency close was attempted
    closed: bool = False  # emergency close succeeded


class PositionProtectionManager:
    def __init__(
        self,
        gateway: ExchangeGateway,
        order_manager: OrderManager,
        event_bus: EventBus,
        config: AppConfig,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        trade_logger=None,
    ) -> None:
        self._gw = gateway
        self._om = order_manager
        self._events = event_bus
        self.cfg = config
        self._sleep = sleep
        self._logger = trade_logger
        self._last_sl_update_at: dict[str, float] = {}

    async def _confirm_position(self, position: Position) -> None:
        """Confirm the exchange position before setting TP/SL (impl doc §5.2 step 3)."""
        try:
            positions = await self._gw.get_positions()
        except Exception:  # noqa: BLE001 - confirmation is best-effort
            return
        match = next(
            (p for p in positions if p.symbol == position.symbol and p.side is not None),
            None,
        )
        if match is not None and match.size > 0:
            # Trust the exchange size for full-position protection.
            position.qty = match.size
            position.avg_entry_price = match.avg_price

    async def protect(self, position: Position) -> ProtectionResult:
        """Set and verify TP/SL for a freshly-filled LIVE position (impl doc §5.2)."""
        pp = self.cfg.position_protection
        tpsl = self.cfg.tpsl
        await self._confirm_position(position)
        tp = position.take_profit_price if tpsl.use_exchange_tp else None
        sl = position.stop_loss_price if tpsl.use_exchange_sl else None

        if tp is None and sl is None:
            position.status = PositionStatus.ACTIVE
            return ProtectionResult(protected=True, tp=tp, sl=sl)

        if pp.verify_tpsl_after_entry and await self._verify(position):
            return await self._activate(position, tp=tp, sl=sl)

        await self._gw.set_trading_stop(
            TradingStopRequest(
                symbol=position.symbol,
                take_profit=tp,
                stop_loss=sl,
                tp_trigger_by=TriggerBy(tpsl.tp_trigger_by),
                sl_trigger_by=TriggerBy(tpsl.sl_trigger_by),
                tpsl_mode=tpsl.tpsl_mode,
            )
        )
        await self._events.publish(
            BotEvent(type=BotEventType.TPSL_SET, symbol=position.symbol,
                     data={"tp": str(tp), "sl": str(sl)})
        )
        if self._logger is not None:
            await self._logger.log_protection(position.symbol, "TPSL_SET", tp=tp, sl=sl)

        if not pp.verify_tpsl_after_entry:
            position.status = PositionStatus.ACTIVE
            return ProtectionResult(protected=True, tp=tp, sl=sl)
        if await self._verify(position):
            return await self._activate(position, tp=tp, sl=sl)

        return await self._emergency_close(position)

    async def _activate(
        self, position: Position, *, tp: Decimal | None, sl: Decimal | None
    ) -> ProtectionResult:
        position.status = PositionStatus.ACTIVE
        await self._events.publish(
            BotEvent(type=BotEventType.TPSL_VERIFIED, symbol=position.symbol)
        )
        if self._logger is not None:
            await self._logger.log_protection(
                position.symbol, "TPSL_VERIFIED", tp=tp, sl=sl
            )
        return ProtectionResult(protected=True, tp=tp, sl=sl)

    async def _verify(self, position: Position) -> bool:
        pp = self.cfg.position_protection
        for attempt in range(pp.verify_tpsl_retry_count):
            state = await self._gw.get_position_tpsl(position.symbol)
            if self._matches_requested_tpsl(position, state):
                return True
            if attempt < pp.verify_tpsl_retry_count - 1:
                await self._sleep(pp.verify_tpsl_retry_interval_sec)
        return False

    def _matches_requested_tpsl(self, position: Position, state) -> bool:
        tolerance = Decimal(str(self.cfg.position_protection.tpsl_verify_tolerance_percent))

        def close_enough(actual: Decimal | None, expected: Decimal) -> bool:
            if actual is None:
                return False
            allowed = abs(expected) * tolerance / Decimal("100")
            return abs(actual - expected) <= allowed

        tpsl = self.cfg.tpsl
        if tpsl.use_exchange_sl:
            if position.stop_loss_price is None:
                return False
            if not close_enough(state.stop_loss, position.stop_loss_price):
                return False
        if tpsl.use_exchange_tp:
            if position.take_profit_price is None:
                return False
            if not close_enough(state.take_profit, position.take_profit_price):
                return False
        return tpsl.use_exchange_sl or tpsl.use_exchange_tp

    async def sync_stop_loss(self, position: Position) -> bool:
        """Sync a ratcheted internal trailing SL to the exchange at a safe cadence."""
        if (
            not self.cfg.position.sync_exchange_sl_with_trailing
            or not self.cfg.tpsl.use_exchange_sl
            or position.stop_loss_price is None
        ):
            return False
        now = time.monotonic()
        last = self._last_sl_update_at.get(position.symbol, 0.0)
        interval = (
            self.cfg.position.runner_mode.min_trailing_update_interval_sec
            if position.runner_mode_active
            else self.cfg.position.min_exchange_sl_update_interval_sec
        )
        if now - last < interval:
            return False
        await self._gw.set_trading_stop(
            TradingStopRequest(
                symbol=position.symbol,
                stop_loss=position.stop_loss_price,
                sl_trigger_by=TriggerBy(self.cfg.tpsl.sl_trigger_by),
                tpsl_mode=self.cfg.tpsl.tpsl_mode,
            )
        )
        self._last_sl_update_at[position.symbol] = now
        if self._logger is not None:
            await self._logger.log_protection(
                position.symbol, "TRAILING_SL_SYNCED",
                sl=position.stop_loss_price,
            )
        return True

    async def _emergency_close(self, position: Position) -> ProtectionResult:
        """TP/SL missing => flatten with reduce-only MARKET (impl doc §5.5, §17.3)."""
        await self._events.publish(
            BotEvent(type=BotEventType.EMERGENCY_TPSL_FAILED, symbol=position.symbol,
                     message="TP/SL set/verify failed")
        )
        if self._logger is not None:
            await self._logger.log_protection(
                position.symbol, "EMERGENCY_TPSL_FAILED", success=False
            )
        exit_side = Side.SELL if position.side == PositionSide.LONG else Side.BUY
        outcome = await self._om.place_exit(
            symbol=position.symbol, side=exit_side, qty=position.qty
        )
        if outcome.is_filled:
            position.status = PositionStatus.CLOSED
            await self._events.publish(
                BotEvent(type=BotEventType.EMERGENCY_CLOSE, symbol=position.symbol,
                         message="position flattened -> ORDER_LOCKED")
            )
            return ProtectionResult(
                protected=False, reason="ORDER_LOCKED", emergency=True, closed=True
            )
        return ProtectionResult(
            protected=False, reason="EMERGENCY_STOP", emergency=True, closed=False
        )

    async def resync(self, position: Position) -> ProtectionResult:
        """Re-apply full-size TP/SL after a manual qty change (impl doc §4.4)."""
        return await self.protect(position)
