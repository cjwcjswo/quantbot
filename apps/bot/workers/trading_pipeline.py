"""Trading pipeline: guard-gated signal->entry->risk->execute->manage (arch §10.4/10.5).

A single ``TradingService`` drives both PAPER and LIVE via a pluggable ``Executor``
(``PaperExecutor`` = PaperExecutionEngine, ``LiveExecutor`` = OrderManager). Every
new entry passes the full guard gauntlet (impl doc §2.1, §15, §16, §7) before it
can reach execution; LIVE entries are only ACTIVE after TP/SL protection (§5).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Awaitable, Callable, Protocol

from apps.bot.runtime.runtime_state import RuntimeState
from packages.config.settings import AppConfig
from packages.core.enums import (
    BotMode,
    BotState,
    EntryMode,
    ExitReason,
    OrderType,
    PositionSide,
    PositionSource,
    PositionStatus,
    ScoutState,
    Side,
    SignalDirection,
)
from packages.core.events import BotEvent, BotEventType
from packages.core.models import (
    Candle,
    Fill,
    IndicatorSnapshot,
    OrderBook,
    Position,
    SymbolMeta,
)
from packages.entry import EntryTimingEngine
from packages.entry.entry_timing_engine import EntryContext
from packages.entry.candle_metrics import metrics_of
from packages.execution import PaperExecutionEngine
from packages.position import PositionActionType, PositionManager
from packages.risk import RiskContext, RiskDecision, RiskManager
from packages.signal import SignalEngine, build_watch_entry

logger = logging.getLogger(__name__)


def _exit_side(position: Position) -> Side:
    return Side.SELL if position.side == PositionSide.LONG else Side.BUY


# --------------------------------------------------------------------------- #
# Executors
# --------------------------------------------------------------------------- #
@dataclass
class OpenResult:
    ok: bool
    fill_price: Decimal
    fill_qty: Decimal
    fee: Decimal = Decimal(0)
    reason: str = ""


@dataclass
class CloseResult:
    fill_price: Decimal
    fill_qty: Decimal
    fee: Decimal = Decimal(0)
    realized: Decimal | None = None  # None => service computes from avg


class Executor(Protocol):
    mode: BotMode

    async def open(
        self, *, symbol: str, side: Side, qty: Decimal, leverage: Decimal,
        best_bid: Decimal, best_ask: Decimal, entry_mode,
        stop_loss: Decimal | None = None, take_profit: Decimal | None = None,
    ) -> OpenResult: ...

    async def close(
        self, *, symbol: str, side: Side, qty: Decimal,
        best_bid: Decimal, best_ask: Decimal, prefer_limit: bool = False,
        limit_price: Decimal | None = None,
    ) -> CloseResult: ...


class PaperExecutor:
    mode = BotMode.PAPER

    def __init__(self, paper_engine: PaperExecutionEngine) -> None:
        self._paper = paper_engine

    async def open(
        self, *, symbol, side, qty, leverage, best_bid, best_ask, entry_mode,
        stop_loss=None, take_profit=None,
    ):
        fill = self._paper.execute_market(symbol, side, qty, best_bid, best_ask)
        return OpenResult(ok=True, fill_price=fill.price, fill_qty=qty, fee=fill.fee)

    async def close(self, *, symbol, side, qty, best_bid, best_ask, prefer_limit=False, limit_price=None):
        fill = self._paper.execute_market(symbol, side, qty, best_bid, best_ask)
        return CloseResult(fill.price, qty, fill.fee, realized=fill.realized_pnl)


class LiveExecutor:
    mode = BotMode.LIVE

    def __init__(self, gateway, order_manager) -> None:
        self._gw = gateway
        self._om = order_manager

    async def open(
        self, *, symbol, side, qty, leverage, best_bid, best_ask, entry_mode,
        stop_loss=None, take_profit=None,
    ):
        await self._gw.set_leverage(symbol, leverage)
        outcome = await self._om.place_entry(
            symbol=symbol, side=side, qty=qty, entry_mode=entry_mode,
            best_bid=best_bid, best_ask=best_ask,
            stop_loss=stop_loss, take_profit=take_profit,
        )
        if not outcome.is_filled:
            return OpenResult(ok=False, fill_price=Decimal(0), fill_qty=Decimal(0),
                              reason=outcome.reason or outcome.status)
        return OpenResult(
            ok=True,
            fill_price=outcome.avg_price or best_ask,
            fill_qty=outcome.filled_qty,
        )

    async def close(self, *, symbol, side, qty, best_bid, best_ask, prefer_limit=False, limit_price=None):
        if prefer_limit:
            outcome = await self._om.place_partial_exit(
                symbol=symbol, side=side, qty=qty, limit_price=limit_price,
                best_bid=best_bid, best_ask=best_ask,
            )
        else:
            outcome = await self._om.place_exit(symbol=symbol, side=side, qty=qty,
                                                order_type=OrderType.MARKET)
        return CloseResult(outcome.avg_price or best_bid, outcome.filled_qty, realized=None)


# --------------------------------------------------------------------------- #
# Guard / market context
# --------------------------------------------------------------------------- #
@dataclass
class GuardSet:
    state_machine: object | None = None  # BotStateMachine
    data_quality: object | None = None
    pre_order_check: object | None = None
    kill_switch: object | None = None
    cooldown: object | None = None
    funding_guard: object | None = None
    clock_guard: object | None = None


@dataclass
class MarketContext:
    now_ms: int = 0
    last_kline_ms: int | None = None
    last_ticker_ms: int | None = None
    last_orderbook_ms: int | None = None
    missing_candles: int = 0
    ticker_price: Decimal | None = None
    kline_close: Decimal | None = None
    orderbook: OrderBook | None = None
    symbol_status: str = "Trading"
    next_funding_time_ms: int | None = None
    funding_rate: Decimal | None = None


@dataclass
class PostExitMfeTracker:
    symbol: str
    side: PositionSide
    exit_price: Decimal
    initial_risk_per_unit: Decimal
    closed_at: datetime
    windows_min: list[int]
    emitted_windows: set[int] = field(default_factory=set)
    best_price: Decimal | None = None


# --------------------------------------------------------------------------- #
# TradingService
# --------------------------------------------------------------------------- #
class TradingService:
    def __init__(
        self,
        config: AppConfig,
        *,
        mode: BotMode,
        signal_engine: SignalEngine,
        entry_engine: EntryTimingEngine,
        risk_manager: RiskManager,
        position_manager: PositionManager,
        state: RuntimeState,
        executor: Executor,
        guards: GuardSet | None = None,
        protection_manager=None,
        trade_logger=None,
        event_bus=None,
    ) -> None:
        self.cfg = config
        self.mode = mode
        self._signals = signal_engine
        self._entry = entry_engine
        self._risk = risk_manager
        self._positions = position_manager
        self._state = state
        self._executor = executor
        self._guards = guards or GuardSet()
        self._protection = protection_manager
        self._logger = trade_logger
        self._events = event_bus
        self._post_exit_mfe: dict[str, PostExitMfeTracker] = {}

    async def _emit(self, event: BotEvent) -> None:
        if self._events is not None:
            await self._events.publish(event)

    def post_exit_mfe_symbols(self) -> list[str]:
        return list(self._post_exit_mfe)

    def start_post_exit_mfe(
        self, position: Position, *, exit_price: Decimal | None = None
    ) -> None:
        c = self.cfg.position.runner_mode
        if (
            not c.enabled
            or not c.log_post_exit_mfe
            or position.initial_risk_per_unit is None
            or position.initial_risk_per_unit <= 0
        ):
            return
        windows = sorted({int(w) for w in c.post_exit_mfe_windows_min if int(w) > 0})
        if not windows:
            return
        self._post_exit_mfe[position.symbol] = PostExitMfeTracker(
            symbol=position.symbol,
            side=position.side,
            exit_price=exit_price or position.stop_loss_price or position.avg_entry_price,
            initial_risk_per_unit=position.initial_risk_per_unit,
            closed_at=position.closed_at or datetime.now(timezone.utc),
            windows_min=windows,
            best_price=exit_price or position.stop_loss_price or position.avg_entry_price,
        )

    async def update_post_exit_mfe(
        self,
        symbol: str,
        *,
        price: Decimal,
        candle_1m: Candle | None = None,
        now: datetime | None = None,
    ) -> None:
        tracker = self._post_exit_mfe.get(symbol)
        if tracker is None:
            return
        now = now or datetime.now(timezone.utc)
        if tracker.side == PositionSide.LONG:
            observed = candle_1m.high if candle_1m is not None else price
            tracker.best_price = max(tracker.best_price or observed, observed)
            mfe = tracker.best_price - tracker.exit_price
        else:
            observed = candle_1m.low if candle_1m is not None else price
            tracker.best_price = min(tracker.best_price or observed, observed)
            mfe = tracker.exit_price - tracker.best_price
        elapsed_min = (now - tracker.closed_at).total_seconds() / 60
        for window in tracker.windows_min:
            if window in tracker.emitted_windows or elapsed_min < window:
                continue
            tracker.emitted_windows.add(window)
            await self._emit(
                BotEvent(
                    type=BotEventType.RUNNER_POST_EXIT_MFE,
                    symbol=symbol,
                    data={
                        "symbol": symbol,
                        "side": tracker.side.value,
                        "window_min": window,
                        "exit_price": str(tracker.exit_price),
                        "best_price_after_exit": str(tracker.best_price),
                        "post_exit_mfe": str(mfe),
                        "post_exit_mfe_r": str(
                            mfe / tracker.initial_risk_per_unit
                        ),
                    },
                )
            )
        if len(tracker.emitted_windows) >= len(tracker.windows_min):
            self._post_exit_mfe.pop(symbol, None)

    def _record_order_failure(self) -> None:
        if self._guards.kill_switch is not None:
            self._guards.kill_switch.record_order_failure()

    def _record_emergency_close_failure(self) -> None:
        if self._guards.kill_switch is not None:
            self._guards.kill_switch.record_emergency_close_failure()

    def _record_slippage_if_breached(
        self, side: Side, fill_price: Decimal, best_bid: Decimal, best_ask: Decimal
    ) -> None:
        if self._guards.kill_switch is None:
            return
        max_slip = Decimal(str(self.cfg.orders.max_slippage_percent))
        if side == Side.BUY and best_ask > 0:
            slip = (fill_price - best_ask) / best_ask * Decimal(100)
        elif side == Side.SELL and best_bid > 0:
            slip = (best_bid - fill_price) / best_bid * Decimal(100)
        else:
            return
        if slip > max_slip:
            self._guards.kill_switch.record_slippage_breach()

    async def _emit_no_entry(
        self,
        *,
        symbol: str,
        sig,
        snapshots: dict[str, IndicatorSnapshot],
        box_high: Decimal,
        box_low: Decimal,
        failed_stage: str,
        reason_code: str,
        entry_mode_candidate: str | None = None,
        anti_chase_reason: str | None = None,
        breakout_quality_reason: str | None = None,
        retest_pending_status: str | None = None,
        extra: dict | None = None,
    ) -> None:
        if sig is None:
            return
        s1 = snapshots.get("1")
        s5 = snapshots.get("5")
        s15 = snapshots.get("15")
        atr1 = s1.atr14 if s1 is not None else None
        if sig.direction == SignalDirection.LONG:
            distance = (box_high - s1.close) / atr1 if s1 and atr1 and atr1 > 0 else None
        else:
            distance = (s1.close - box_low) / atr1 if s1 and atr1 and atr1 > 0 else None
        ema_gap = None
        if (
            s15 is not None
            and s15.ema20 is not None
            and s15.ema50 is not None
            and s15.close > 0
        ):
            ema_gap = abs(s15.ema20 - s15.ema50) / s15.close * Decimal(100)
        pending = self._entry.retests.get(symbol)
        data = {
            "strategy_signal_side": sig.direction.value,
            "signal_score": str(sig.score),
            "failed_stage": failed_stage,
            "reason_code": reason_code,
            "entry_mode_candidate": entry_mode_candidate,
            "rsi_1m": str(s1.rsi14) if s1 and s1.rsi14 is not None else None,
            "rsi_5m": str(s5.rsi14) if s5 and s5.rsi14 is not None else None,
            "volume_ratio_1m": str(s1.volume_ratio)
            if s1 and s1.volume_ratio is not None
            else None,
            "volume_ratio_5m": str(s5.volume_ratio)
            if s5 and s5.volume_ratio is not None
            else None,
            "atr_percent": str(s1.atr_percent)
            if s1 and s1.atr_percent is not None
            else None,
            "ema_gap_15m": str(ema_gap) if ema_gap is not None else None,
            "ema_slope_atr_15m": str(s15.ema20_slope_atr)
            if s15 and s15.ema20_slope_atr is not None
            else None,
            "distance_to_box_atr": str(distance) if distance is not None else None,
            "anti_chase_reason": anti_chase_reason,
            "breakout_quality_reason": breakout_quality_reason,
            "retest_pending_status": retest_pending_status
            or (
                f"WAITING:{pending.bars_waited}"
                if pending is not None
                else "NONE"
            ),
        }
        if extra:
            data.update(extra)
        await self._emit(
            BotEvent(
                type=BotEventType.NO_ENTRY_REASON,
                symbol=symbol,
                message=reason_code,
                data={k: v for k, v in data.items() if v is not None},
            )
        )

    @staticmethod
    def _gate_reason_code(reason: str) -> str:
        if reason.startswith("DATA_QUALITY:"):
            return reason.removeprefix("DATA_QUALITY:")
        if reason.startswith("FUNDING:"):
            return reason.removeprefix("FUNDING:")
        if reason.startswith("PRE_ORDER:INSUFFICIENT_DEPTH"):
            return "PRE_ORDER_INSUFFICIENT_DEPTH"
        if reason.startswith("PRE_ORDER:"):
            return reason.removeprefix("PRE_ORDER:")
        if "COOLDOWN" in reason:
            return "COOLDOWN_ACTIVE"
        if reason.startswith("KILL_SWITCH:"):
            return "KILL_SWITCH_ACTIVE"
        return reason

    def _transition_after_protection_failure(self, reason: str) -> None:
        sm = self._guards.state_machine
        if sm is None:
            return
        target = (
            BotState.ORDER_LOCKED
            if reason == "ORDER_LOCKED"
            else BotState.EMERGENCY_STOP
            if reason == "EMERGENCY_STOP"
            else None
        )
        if target is None:
            return
        try:
            sm.transition(target, reason="TP/SL protection failure")
        except Exception:
            sm.force(target, reason="TP/SL protection failure")

    def _position_protection_status(self, pos: Position) -> str:
        needs_sl = self.cfg.tpsl.use_exchange_sl
        needs_tp = self.cfg.tpsl.use_exchange_tp
        if not needs_sl and not needs_tp:
            return "NOT_REQUIRED"
        if needs_sl and pos.stop_loss_price is None:
            return "TPSL_PENDING"
        if needs_tp and pos.take_profit_price is None:
            return "TPSL_PENDING"
        return "TPSL_OK"

    # ------------------------------------------------------------------ #
    # guard gates
    # ------------------------------------------------------------------ #
    def _pre_gate(
        self,
        symbol: str,
        direction: SignalDirection,
        snapshot_1m: IndicatorSnapshot,
        market: MarketContext | None,
    ) -> str | None:
        g = self._guards
        if g.state_machine is not None and not g.state_machine.can_enter_new_position():
            return "NOT_RUNNING"
        if self._state.new_entries_paused():
            return "ENTRIES_PAUSED"
        if g.kill_switch is not None:
            tripped = g.kill_switch.evaluate()
            if tripped:
                return f"KILL_SWITCH:{tripped}"
        if g.cooldown is not None and g.cooldown.in_global_cooldown():
            return "GLOBAL_COOLDOWN"
        if g.cooldown is not None and g.cooldown.in_symbol_cooldown(symbol):
            return "SYMBOL_COOLDOWN"
        if market is not None:
            if g.data_quality is not None:
                reason = g.data_quality.check(
                    now_ms=market.now_ms, last_kline_ms=market.last_kline_ms,
                    last_ticker_ms=market.last_ticker_ms,
                    last_orderbook_ms=market.last_orderbook_ms,
                    missing_candles=market.missing_candles,
                    ticker_price=market.ticker_price, kline_close=market.kline_close,
                    indicators=snapshot_1m,
                    require_orderbook=market.last_orderbook_ms is not None,
                )
                if reason:
                    return f"DATA_QUALITY:{reason}"
            if g.funding_guard is not None:
                reason = g.funding_guard.block_new_entry(
                    now_ms=market.now_ms,
                    next_funding_time_ms=market.next_funding_time_ms,
                    funding_rate=market.funding_rate,
                    direction=direction,
                )
                if reason:
                    return f"FUNDING:{reason}"
            if self.cfg.symbol_status.block_if_status_not_trading and market.symbol_status != "Trading":
                return "SYMBOL_NOT_TRADING"
        return None

    def _post_gate(
        self, entry_mode, notional: Decimal, market: MarketContext | None
    ) -> str | None:
        g = self._guards
        if g.cooldown is not None and g.cooldown.in_entry_mode_cooldown(entry_mode):
            return "ENTRY_MODE_COOLDOWN"
        if g.pre_order_check is not None and market is not None and market.orderbook is not None and g.clock_guard is not None:
            slip = (
                Decimal(str(self.cfg.paper.market_slippage_percent))
                if self.mode == BotMode.PAPER
                else Decimal(str(self.cfg.orders.max_slippage_percent))
            )
            reason = g.pre_order_check.check(
                orderbook=market.orderbook, order_notional=notional,
                expected_slippage_percent=slip, symbol_status=market.symbol_status,
                clock=g.clock_guard,
            )
            if reason:
                return f"PRE_ORDER:{reason}"
        return None

    # ------------------------------------------------------------------ #
    async def evaluate_entry(
        self,
        *,
        symbol: str,
        snapshots: dict[str, IndicatorSnapshot],
        candles_1m: list,
        box_high: Decimal,
        box_low: Decimal,
        symbol_meta: SymbolMeta,
        equity: Decimal,
        entry_price: Decimal,
        best_bid: Decimal,
        best_ask: Decimal,
        market: MarketContext | None = None,
        orderbook_provider: Callable[
            [], Awaitable[tuple[OrderBook, int | None]]
        ] | None = None,
        daily_loss_percent: Decimal = Decimal(0),
        consecutive_losses: int = 0,
    ) -> Position | None:
        signals = self._signals.generate(symbol, snapshots)
        if not signals:
            return None
        sig = signals[0]

        blocked = self._pre_gate(symbol, sig.direction, snapshots["1"], market)
        if blocked is not None:
            await self._emit_no_entry(
                symbol=symbol,
                sig=sig,
                snapshots=snapshots,
                box_high=box_high,
                box_low=box_low,
                failed_stage="pre_gate",
                reason_code=self._gate_reason_code(blocked),
            )
            await self._emit(BotEvent(type=BotEventType.DATA_QUALITY_BLOCK,
                                      symbol=symbol, message=blocked))
            return None

        ctx = EntryContext(
            symbol=symbol, direction=sig.direction,
            snapshot_1m=snapshots["1"], snapshot_5m=snapshots["5"],
            snapshot_15m=snapshots["15"], candles_1m=candles_1m,
            box_high=box_high, box_low=box_low,
            signal_score=sig.score, signal_reason=sig.reason,
        )
        decision = self._entry.evaluate(ctx)
        if decision is None:
            reason = self._entry.last_no_entry_reason or {
                "failed_stage": "entry_timing",
                "reason_code": "NO_ENTRY_DECISION",
            }
            await self._emit_no_entry(
                symbol=symbol,
                sig=sig,
                snapshots=snapshots,
                box_high=box_high,
                box_low=box_low,
                failed_stage=reason.get("failed_stage", "entry_timing"),
                reason_code=reason.get("reason_code", "NO_ENTRY_DECISION"),
                entry_mode_candidate=reason.get("entry_mode_candidate"),
                anti_chase_reason=reason.get("anti_chase_reason"),
                breakout_quality_reason=reason.get("breakout_quality_reason"),
                retest_pending_status=reason.get("retest_pending_status"),
            )
            return None

        atr1 = snapshots["1"].atr14 or Decimal(0)
        risk_ctx = RiskContext(
            equity=equity, open_positions=self._state.active_bot_positions(),
            daily_loss_percent=daily_loss_percent, consecutive_losses=consecutive_losses,
        )
        rd = self._risk.approve(decision, entry_price=entry_price, atr=atr1,
                                symbol_meta=symbol_meta, ctx=risk_ctx)
        if not rd.approved:
            await self._emit_no_entry(
                symbol=symbol,
                sig=sig,
                snapshots=snapshots,
                box_high=box_high,
                box_low=box_low,
                failed_stage="risk",
                reason_code="RISK_REJECTED",
                entry_mode_candidate=decision.entry_mode.value,
                extra={"risk_reason": rd.reason, **(rd.stop_metadata or {})},
            )
            await self._emit(BotEvent(type=BotEventType.SIGNAL, symbol=symbol,
                                      message=f"rejected: {rd.reason}"))
            return None

        if (
            market is not None
            and market.orderbook is None
            and orderbook_provider is not None
            and self._guards.pre_order_check is not None
        ):
            market.orderbook, market.last_orderbook_ms = await orderbook_provider()

        post_blocked = self._post_gate(decision.entry_mode, rd.notional, market)
        if post_blocked is not None:
            await self._emit_no_entry(
                symbol=symbol,
                sig=sig,
                snapshots=snapshots,
                box_high=box_high,
                box_low=box_low,
                failed_stage="post_gate",
                reason_code=self._gate_reason_code(post_blocked),
                entry_mode_candidate=decision.entry_mode.value,
            )
            await self._emit(BotEvent(type=BotEventType.DATA_QUALITY_BLOCK,
                                      symbol=symbol, message=post_blocked))
            return None

        side = Side.BUY if sig.direction == SignalDirection.LONG else Side.SELL
        attach_sl = (
            rd.stop_loss_price
            if (
                self.mode == BotMode.LIVE
                and self.cfg.tpsl.use_exchange_tpsl
                and self.cfg.tpsl.use_exchange_sl
            )
            else None
        )
        attach_tp = (
            rd.take_profit_price
            if (
                self.mode == BotMode.LIVE
                and self.cfg.tpsl.use_exchange_tpsl
                and self.cfg.tpsl.use_exchange_tp
            )
            else None
        )
        self._state.begin_position_update(symbol)
        try:
            opened = await self._executor.open(
                symbol=symbol, side=side, qty=rd.qty, leverage=rd.leverage,
                best_bid=best_bid, best_ask=best_ask, entry_mode=decision.entry_mode,
                stop_loss=attach_sl, take_profit=attach_tp,
            )
            if not opened.ok or opened.fill_qty <= 0:
                if decision.entry_mode == EntryMode.BREAKOUT_CONFIRM:
                    level = box_high if sig.direction == SignalDirection.LONG else box_low
                    self._entry.retests.register(symbol, sig.direction, level)
                self._record_order_failure()
                await self._emit(BotEvent(type=BotEventType.ORDER_FAILED, symbol=symbol,
                                          message=opened.reason))
                return None
            self._record_slippage_if_breached(side, opened.fill_price, best_bid, best_ask)

            pos = Position(
                symbol=symbol, side=rd.side, status=PositionStatus.PENDING,
                source=PositionSource.BOT, qty=opened.fill_qty,
                avg_entry_price=opened.fill_price, leverage=rd.leverage,
                stop_loss_price=rd.stop_loss_price, take_profit_price=rd.take_profit_price,
                initial_risk_per_unit=abs(opened.fill_price - rd.stop_loss_price),
                entry_mode=decision.entry_mode, signal_score=sig.score,
                strategy_id=sig.strategy, strategy_reason=sig.reason, fees_paid=opened.fee,
                breakout_level=box_high if rd.side == PositionSide.LONG else box_low,
                scout_state=ScoutState.SCOUT_PENDING
                if (
                    decision.entry_mode == EntryMode.PRE_BREAKOUT_SCOUT
                    and self.cfg.position.scout_management.enabled
                )
                else ScoutState.NONE,
                scout_entry_box_high=box_high
                if decision.entry_mode == EntryMode.PRE_BREAKOUT_SCOUT
                else None,
                scout_entry_box_low=box_low
                if decision.entry_mode == EntryMode.PRE_BREAKOUT_SCOUT
                else None,
                scout_entry_box_mid=(box_high + box_low) / Decimal("2")
                if decision.entry_mode == EntryMode.PRE_BREAKOUT_SCOUT
                else None,
                scout_entry_level=box_high
                if (
                    decision.entry_mode == EntryMode.PRE_BREAKOUT_SCOUT
                    and rd.side == PositionSide.LONG
                )
                else box_low
                if decision.entry_mode == EntryMode.PRE_BREAKOUT_SCOUT
                else None,
                scout_entry_bar_index=0
                if decision.entry_mode == EntryMode.PRE_BREAKOUT_SCOUT
                else None,
            )
            self._state.positions[symbol] = pos

            # Activation: LIVE requires TP/SL protection (§5); PAPER stores virtual levels.
            if self.mode == BotMode.LIVE and self._protection is not None:
                result = await self._protection.protect(pos)
                if not result.protected:
                    self._record_order_failure()
                    if result.reason == "EMERGENCY_STOP":
                        self._record_emergency_close_failure()
                    self._transition_after_protection_failure(result.reason)
                    await self._emit(BotEvent(type=BotEventType.ORDER_FAILED, symbol=symbol,
                                              message=f"tpsl:{result.reason}"))
                    return None
            else:
                self._positions.mark_active_paper(pos)
        finally:
            self._state.end_position_update(symbol)

        if self._logger is not None:
            protection = self._position_protection_status(pos)
            await self._logger.log_signal(sig, entry_mode=decision.entry_mode.value)
            await self._logger.log_fill(
                self._as_fill(opened, symbol, side), mode=self.mode.value
            )
            await self._logger.log_position(
                pos, mode=self.mode.value, strategy_id=sig.strategy,
                protection_status=protection,
            )
        opened_data = {
            "qty": str(pos.qty),
            "entry": str(pos.avg_entry_price),
            "mode": decision.entry_mode.value,
            "position_fraction": str(decision.position_fraction),
        }
        if rd.stop_metadata:
            opened_data.update(rd.stop_metadata)
        if decision.compression_mode is not None:
            opened_data.update(
                {
                    "compression_mode": decision.compression_mode,
                    "has_compression": decision.has_compression,
                    "scout_score": str(decision.score),
                    "required_scout_score": str(decision.required_score)
                    if decision.required_score is not None
                    else None,
                    "compression_bonus_applied": str(decision.compression_bonus_applied)
                    if decision.compression_bonus_applied is not None
                    else None,
                }
            )
        await self._emit(
            BotEvent(
                type=BotEventType.POSITION_OPENED,
                symbol=symbol,
                data={k: v for k, v in opened_data.items() if v is not None},
            )
        )
        if pos.scout_state == ScoutState.SCOUT_PENDING:
            last_candle = candles_1m[-1] if candles_1m else None
            metrics = metrics_of(last_candle) if last_candle is not None else None
            snapshot_1m = snapshots["1"]
            await self._emit(
                BotEvent(
                    type=BotEventType.SCOUT_PENDING_STARTED,
                    symbol=symbol,
                    data={
                        "symbol": symbol,
                        "side": pos.side.value,
                        "entry_price": str(pos.avg_entry_price),
                        "current_price": str(pos.avg_entry_price),
                        "scout_state": pos.scout_state.value,
                        "bars_since_entry": pos.bars_since_entry,
                        "box_high": str(pos.scout_entry_box_high),
                        "box_low": str(pos.scout_entry_box_low),
                        "box_mid": str(pos.scout_entry_box_mid),
                        "scout_entry_level": str(pos.scout_entry_level),
                        "scout_defensive_reduction_count": (
                            pos.scout_defensive_reduction_count
                        ),
                        "reason": "PRE_BREAKOUT_SCOUT_ENTRY",
                        "rsi14": str(snapshot_1m.rsi14)
                        if snapshot_1m.rsi14 is not None
                        else None,
                        "ema20": str(snapshot_1m.ema20)
                        if snapshot_1m.ema20 is not None
                        else None,
                        "volume_ratio": str(snapshot_1m.volume_ratio)
                        if snapshot_1m.volume_ratio is not None
                        else None,
                        "body_ratio": str(metrics.body_ratio)
                        if metrics is not None and metrics.valid
                        else None,
                        "close_position_in_range": str(
                            metrics.close_position_in_range
                        )
                        if metrics is not None and metrics.valid
                        else None,
                    },
                )
            )
        return pos

    def preview_watch(
        self,
        *,
        symbol: str,
        snapshots: dict[str, IndicatorSnapshot],
        box_high: Decimal,
        box_low: Decimal,
        last_price: Decimal,
    ) -> dict:
        """Read-only entry preview for the dashboard watch list (arch §6.18).

        Generates signals (a pure operation) but never runs the stateful
        EntryTimingEngine or places an order, so it is safe to call every cycle.
        """
        signals = self._signals.generate(symbol, snapshots)
        margin = Decimal(str(self.cfg.entry.breakout_confirm.close_beyond_boundary_atr))
        scout = self.cfg.entry.pre_breakout
        return build_watch_entry(
            symbol=symbol,
            signal=signals[0] if signals else None,
            snapshot_1m=snapshots["1"],
            snapshot_15m=snapshots["15"],
            box_high=box_high,
            box_low=box_low,
            last_price=last_price,
            breakout_margin_atr=margin,
            near_zone_atr=Decimal(str(scout.score_near_box_atr)),
            scout_zone_atr=Decimal(str(scout.max_distance_to_box_atr)),
        )

    async def close_position(
        self,
        symbol: str,
        *,
        best_bid: Decimal,
        best_ask: Decimal,
        reason: ExitReason = ExitReason.MANUAL_CLOSE,
        close_percent: Decimal = Decimal("100"),
    ) -> bool:
        pos = self._state.get_position(symbol)
        if pos is None or not pos.is_bot_managed:
            return False
        if pos.status not in (PositionStatus.ACTIVE, PositionStatus.PENDING):
            return False
        pct = min(Decimal("100"), max(Decimal("0"), close_percent))
        if pct <= 0:
            return False
        qty = pos.qty * pct / Decimal("100")
        if qty <= 0:
            return False
        full = qty >= pos.qty
        await self._close(
            pos, qty, reason, best_bid, best_ask, full=full, prefer_limit=False
        )
        return True

    async def manage(
        self, *, symbol: str, price: Decimal, atr: Decimal,
        best_bid: Decimal, best_ask: Decimal, candle_1m=None,
        snapshot_1m: IndicatorSnapshot | None = None,
        snapshot_5m: IndicatorSnapshot | None = None,
        volume_ratio: Decimal | None = None,
        funding_rate: Decimal | None = None,
    ) -> list:
        pos = self._state.get_position(symbol)
        if pos is None or not pos.is_bot_managed or pos.status != PositionStatus.ACTIVE:
            return []
        actions = []
        if (
            self._guards.funding_guard is not None
            and self._guards.funding_guard.should_reduce_position(funding_rate, pos.side)
        ):
            qty = pos.qty * Decimal("0.5")
            await self._close(
                pos, qty, ExitReason.FUNDING_GUARD, best_bid, best_ask,
                full=False, prefer_limit=False,
            )
            actions.append({"type": "FUNDING_REDUCE", "qty": qty})
            if pos.qty <= 0:
                return actions
        position_actions = self._positions.evaluate(
            pos, price=price, atr=atr, candle_1m=candle_1m,
            snapshot_1m=snapshot_1m, snapshot_5m=snapshot_5m,
            volume_ratio=volume_ratio,
        )
        actions.extend(position_actions)
        for action in position_actions:
            if action.type == PositionActionType.SCOUT_EVENT:
                await self._emit_scout_action(pos, action)
            elif action.type == PositionActionType.EXIT:
                await self._close(pos, pos.qty, action.reason, best_bid, best_ask,
                                  full=True, prefer_limit=False)
            elif action.type == PositionActionType.PARTIAL_TP:
                prev_qty = pos.qty
                await self._close(pos, action.qty, action.reason, best_bid, best_ask,
                                  full=False, prefer_limit=True)  # §12.2 LIMIT-first
                if pos.status != PositionStatus.CLOSED and pos.qty < prev_qty:
                    runner_actions = self._positions.activate_runner_after_partial_tp(
                        pos,
                        price=price,
                        atr=atr,
                        candle_1m=candle_1m,
                        snapshot_1m=snapshot_1m,
                        snapshot_5m=snapshot_5m,
                        volume_ratio=volume_ratio,
                    )
                    actions.extend(runner_actions)
                    for runner_action in runner_actions:
                        if runner_action.type == PositionActionType.SCOUT_EVENT:
                            await self._emit_scout_action(pos, runner_action)
                        elif runner_action.type == PositionActionType.TRAIL_UPDATE:
                            await self._sync_trailing_stop(pos, runner_action)
            elif action.type == PositionActionType.REDUCE:
                await self._close(pos, action.qty, action.reason, best_bid, best_ask,
                                  full=False, prefer_limit=False)
                await self._emit_scout_action(pos, action)
            elif action.type == PositionActionType.TRAIL_UPDATE:
                pos.stop_loss_price = action.new_stop
                await self._sync_trailing_stop(pos, action)
                if self._logger is not None:
                    await self._logger.log_position(
                        pos,
                        mode=self.mode.value,
                        protection_status=self._position_protection_status(pos),
                    )
        return actions

    async def _sync_trailing_stop(self, pos: Position, action) -> None:
        if self.mode != BotMode.LIVE or self._protection is None:
            return
        if pos.runner_mode_active:
            try:
                synced = await self._protection.sync_stop_loss(pos)
            except Exception as exc:  # noqa: BLE001 - retry on next cycle
                pos.runner_exchange_sl_update_failures += 1
                data = dict(action.data or {})
                data.update(
                    {
                        "consecutive_failures": pos.runner_exchange_sl_update_failures,
                        "error": str(exc),
                    }
                )
                await self._emit(
                    BotEvent(
                        type=BotEventType.RUNNER_EXCHANGE_SL_UPDATE_FAILED,
                        symbol=pos.symbol,
                        message="Runner exchange SL update failed",
                        data={k: v for k, v in data.items() if v is not None},
                    )
                )
                return
            if synced:
                pos.runner_exchange_sl_update_failures = 0
                await self._emit(
                    BotEvent(
                        type=BotEventType.RUNNER_EXCHANGE_SL_UPDATED,
                        symbol=pos.symbol,
                        data={k: v for k, v in (action.data or {}).items()
                              if v is not None},
                    )
                )
            return
        await self._protection.sync_stop_loss(pos)

    async def _emit_scout_action(self, pos, action) -> None:
        if action.event_type is None:
            return
        await self._emit(
            BotEvent(
                type=BotEventType(action.event_type),
                symbol=pos.symbol,
                data={k: v for k, v in (action.data or {}).items() if v is not None},
            )
        )

    async def _close(self, pos, qty, reason, best_bid, best_ask, *, full, prefer_limit):
        self._state.begin_position_update(pos.symbol)
        try:
            limit_price = pos.take_profit_price if prefer_limit else None
            result = await self._executor.close(
                symbol=pos.symbol, side=_exit_side(pos), qty=qty,
                best_bid=best_bid, best_ask=best_ask,
                prefer_limit=prefer_limit, limit_price=limit_price,
            )
            if pos.status == PositionStatus.CLOSED:
                return
            filled_qty = result.fill_qty
            if filled_qty <= 0:
                return
            direction = Decimal(1) if pos.side == PositionSide.LONG else Decimal(-1)
            realized = (
                result.realized
                if result.realized is not None
                else (result.fill_price - pos.avg_entry_price) * filled_qty * direction
            )
            pos.realized_pnl += realized
            pos.fees_paid += result.fee
            pos.qty -= filled_qty
            if full or pos.qty <= 0:
                pos.status = PositionStatus.CLOSED
                pos.closed_at = datetime.now(timezone.utc)
                pos.exit_reason = reason
            if self._logger is not None:
                await self._logger.log_fill(
                    self._as_fill_raw(
                        pos.symbol, _exit_side(pos), result.fill_price,
                        filled_qty, result.fee,
                    ),
                    realized_pnl=str(realized), mode=self.mode.value,
                )
                await self._logger.log_position(pos, mode=self.mode.value)
                if pos.status == PositionStatus.CLOSED:
                    r_mult = None
                    if (
                        pos.initial_risk_per_unit
                        and pos.initial_risk_per_unit > 0
                        and filled_qty > 0
                    ):
                        r_mult = str(
                            pos.realized_pnl / (pos.initial_risk_per_unit * filled_qty)
                        )
                    await self._logger.log_trade(
                        symbol=pos.symbol, side=pos.side.value, qty=str(filled_qty),
                        entry_price=str(pos.avg_entry_price),
                        exit_price=str(result.fill_price),
                        realized_pnl=str(pos.realized_pnl),
                        exit_reason=reason.value if reason else None,
                        strategy_id=pos.strategy_id or None,
                        entry_mode=pos.entry_mode.value if pos.entry_mode else None,
                        mode=self.mode.value, leverage=str(pos.leverage),
                        fees=str(pos.fees_paid),
                        gross_pnl=str(pos.realized_pnl + pos.fees_paid),
                        net_pnl=str(pos.realized_pnl), r_multiple=r_mult,
                        opened_at=pos.opened_at, closed_at=pos.closed_at,
                    )
            if pos.status == PositionStatus.CLOSED:
                if reason == ExitReason.RUNNER_TRAILING_STOP:
                    self.start_post_exit_mfe(pos, exit_price=result.fill_price)
                if self._guards.cooldown is not None and pos.entry_mode is not None:
                    self._guards.cooldown.record_result(
                        pos.symbol, pos.entry_mode, is_win=pos.realized_pnl > 0
                    )
                if self._guards.kill_switch is not None:
                    self._guards.kill_switch.record_trade_result(
                        is_win=pos.realized_pnl > 0
                    )
                await self._emit(
                    BotEvent(
                        type=BotEventType.POSITION_CLOSED,
                        symbol=pos.symbol,
                        data={
                            "realized_pnl": str(pos.realized_pnl),
                            "reason": reason.value if reason else None,
                        },
                    )
                )
        finally:
            self._state.end_position_update(pos.symbol)

    @staticmethod
    def _as_fill(opened: OpenResult, symbol: str, side: Side) -> Fill:
        return Fill(symbol=symbol, order_id="exec", side=side,
                    price=opened.fill_price, qty=opened.fill_qty, fee=opened.fee)

    @staticmethod
    def _as_fill_raw(symbol, side, price, qty, fee) -> Fill:
        return Fill(symbol=symbol, order_id="exec", side=side, price=price, qty=qty, fee=fee)


# Backwards-compatible alias.
PaperTradingService = TradingService
