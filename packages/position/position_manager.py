"""PositionManager: bot position lifecycle management (impl doc §14, arch doc §6.21).

``evaluate`` is a pure, per-1m-bar decision function returning the actions to take
for one bot-managed position: partial take-profit, trailing/runner updates,
stagnation exit, scenario-invalidation exit and the max-holding-time exit. Order
execution (LIVE OrderManager / PAPER engine) is applied by the caller, keeping
this logic deterministic and unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from packages.config.settings import AppConfig
from packages.core.enums import (
    EntryMode,
    ExitReason,
    PositionSide,
    PositionStatus,
    ScoutState,
)
from packages.core.models import Candle, IndicatorSnapshot, Position
from packages.entry.candle_metrics import metrics_of


class PositionActionType(StrEnum):
    PARTIAL_TP = "PARTIAL_TP"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    TRAIL_UPDATE = "TRAIL_UPDATE"
    SCOUT_EVENT = "SCOUT_EVENT"


@dataclass(frozen=True)
class PositionAction:
    type: PositionActionType
    qty: Decimal | None = None
    reason: ExitReason | None = None
    new_stop: Decimal | None = None
    event_type: str | None = None
    data: dict | None = None


class PositionManager:
    def __init__(self, config: AppConfig) -> None:
        self.cfg = config
        p = config.position
        self.partial_r = Decimal(str(p.partial_take_profit_r))
        self.partial_fraction = Decimal(str(p.partial_take_profit_fraction))
        self.trailing_start_r = Decimal(str(p.trailing_start_r))
        self.trailing_mult = Decimal(str(p.trailing_atr_multiplier))
        self.trailing_ext_after_r = Decimal(str(p.trailing_extended_after_r))
        self.trailing_ext_mult = Decimal(str(p.trailing_extended_atr_multiplier))
        self.max_holding_minutes = p.max_holding_minutes
        # internal per-symbol tracking
        self._max_r: dict[str, Decimal] = {}
        self._stag_reduced: set[str] = set()
        self._scenario_recovery: dict[str, int] = {}
        self._scenario_reduced: set[tuple[str, str]] = set()
        self._break_level_fail_closes: dict[tuple[str, str], tuple[int | None, int]] = {}
        self._scout_scenario_invalid_closes: dict[
            tuple[str, str], tuple[int | None, int]
        ] = {}
        self._scout_ema_reclaim_counts: dict[str, int] = {}
        self._runner_ema_break_counts: dict[str, int] = {}
        self._runner_weak_signal_counts: dict[str, int] = {}
        self._runner_weak_signal_open_times: dict[str, int] = {}
        self._stagnation_delay_emitted: set[tuple[str, str, str]] = set()

    def mark_active_paper(self, position: Position) -> None:
        """PAPER positions become ACTIVE once virtual fill + SL/TP stored (§14.1)."""
        position.status = PositionStatus.ACTIVE

    # ------------------------------------------------------------------ #
    def r_multiple(self, position: Position, price: Decimal) -> Decimal:
        risk = position.initial_risk_per_unit
        if risk is None or risk <= 0:
            return Decimal(0)
        if position.side == PositionSide.LONG:
            return (price - position.avg_entry_price) / risk
        return (position.avg_entry_price - price) / risk

    def evaluate(
        self,
        position: Position,
        *,
        price: Decimal,
        atr: Decimal,
        candle_1m: Candle | None = None,
        snapshot_1m: IndicatorSnapshot | None = None,
        snapshot_5m: IndicatorSnapshot | None = None,
        volume_ratio: Decimal | None = None,
        now: datetime | None = None,
    ) -> list[PositionAction]:
        if not position.is_bot_managed or position.status != PositionStatus.ACTIVE:
            return []

        now = now or datetime.now(timezone.utc)
        self._advance_bar_counter(position, candle_1m)
        self._update_extremes(position, price, candle_1m)
        r = self.r_multiple(position, price)
        max_r = max(self._max_r.get(position.symbol, Decimal(0)), r)
        self._max_r[position.symbol] = max_r

        # 1. max holding time (§14, position.max_holding_minutes)
        held_min = (now - position.opened_at).total_seconds() / 60
        if held_min >= self.max_holding_minutes:
            return [self._exit(position, ExitReason.MAX_HOLDING_TIME)]

        prefix_actions, apply_general_management = self._scout_management_action(
            position,
            price=price,
            atr=atr,
            candle=candle_1m,
            snapshot_1m=snapshot_1m,
            volume_ratio=volume_ratio,
            max_r=max_r,
            now=now,
        )
        if not apply_general_management:
            return prefix_actions

        runner_events = self._runner_state_actions(
            position,
            price=price,
            atr=atr,
            candle=candle_1m,
            snapshot_1m=snapshot_1m,
            snapshot_5m=snapshot_5m,
            volume_ratio=volume_ratio,
            max_r=max_r,
            current_r=r,
            now=now,
        )

        actions: list[PositionAction] = list(prefix_actions) + runner_events

        # 2. partial take-profit (§14.2). Take profit before trailing checks so
        # the first +2R touch cannot skip the planned half close.
        if not position.partial_tp_done and r >= self.partial_r:
            position.partial_tp_done = True
            actions.append(
                PositionAction(
                    type=PositionActionType.PARTIAL_TP,
                    qty=self._round_qty(position.qty * self.partial_fraction),
                    reason=ExitReason.PARTIAL_TAKE_PROFIT,
                )
            )
            return actions

        # 2. trailing stop breach (§14.3)
        if max_r >= self.trailing_start_r:
            position.trailing_active = True
            trail_stop = self._trail_stop(position, atr, max_r)
            effective_stop = self._effective_stop(position, trail_stop)
            if self._stop_breached(position, price, effective_stop):
                reason = (
                    ExitReason.RUNNER_TRAILING_STOP
                    if position.runner_mode_active
                    else ExitReason.TRAILING_STOP
                )
                actions = prefix_actions + runner_events
                if position.runner_mode_active:
                    actions.append(
                        self._runner_event(
                            position,
                            "RUNNER_TRAILING_STOP",
                            price=price,
                            atr=atr,
                            current_r=r,
                            max_r=max_r,
                            old_stop=position.stop_loss_price,
                            new_stop=effective_stop,
                            reason="RUNNER_TRAILING_STOP",
                        )
                    )
                return actions + [self._exit(position, reason)]

        # 3. scenario invalidation (§14.5)
        if (
            position.runner_mode_active
            and self._scenario_invalid(
                position,
                snapshot_5m,
                candle_1m,
                volume_ratio,
                include_counter_candle=False,
            )
        ):
            return (
                prefix_actions
                + runner_events
                + [
                    self._runner_event(
                        position,
                        "RUNNER_SCENARIO_INVALID",
                        price=price,
                        atr=atr,
                        current_r=r,
                        max_r=max_r,
                        reason="RUNNER_SCENARIO_INVALID",
                    ),
                    self._exit(position, ExitReason.RUNNER_SCENARIO_INVALID),
                ]
            )
        scenario = None
        if not position.runner_mode_active:
            scenario = self._scenario_action(
                position,
                r,
                snapshot_5m,
                candle_1m,
                volume_ratio,
                price=price,
                atr=atr,
            )
        if scenario is not None:
            return prefix_actions + runner_events + [scenario]

        # 4. stagnation (§14.4)
        stagnation = None if position.runner_mode_active else self._stagnation_action(
            position, max_r, current_r=r, price=price, atr=atr
        )
        if stagnation is not None:
            return prefix_actions + runner_events + [stagnation]

        # 6. trailing-stop ratchet update
        if position.trailing_active:
            trail_stop = self._trail_stop(position, atr, max_r)
            new_stop = self._ratchet(position, trail_stop)
            if new_stop is not None and self._runner_trailing_update_allowed(
                position, new_stop, atr, now
            ):
                old_stop = position.stop_loss_price
                position.stop_loss_price = new_stop
                self._record_runner_trailing_update(position, new_stop, now)
                if position.runner_mode_active:
                    actions.append(
                        self._runner_event(
                            position,
                            "RUNNER_TRAILING_UPDATED",
                            price=price,
                            atr=atr,
                            current_r=r,
                            max_r=max_r,
                            old_stop=old_stop,
                            new_stop=new_stop,
                        )
                    )
                actions.append(
                    PositionAction(type=PositionActionType.TRAIL_UPDATE, new_stop=new_stop)
                )
        return actions

    # ------------------------------------------------------------------ #
    @staticmethod
    def _advance_bar_counter(position: Position, candle: Candle | None) -> None:
        if candle is None or candle.open_time_ms <= 0:
            position.bars_since_entry += 1
            return
        last_open_time = position.last_evaluated_1m_open_time_ms
        if last_open_time == candle.open_time_ms:
            return
        position.last_evaluated_1m_open_time_ms = candle.open_time_ms
        position.bars_since_entry += 1

    # ------------------------------------------------------------------ #
    # Runner Mode after partial TP
    # ------------------------------------------------------------------ #
    def activate_runner_after_partial_tp(
        self,
        position: Position,
        *,
        price: Decimal,
        atr: Decimal,
        candle_1m: Candle | None = None,
        snapshot_1m: IndicatorSnapshot | None = None,
        snapshot_5m: IndicatorSnapshot | None = None,
        volume_ratio: Decimal | None = None,
        now: datetime | None = None,
    ) -> list[PositionAction]:
        c = self.cfg.position.runner_mode
        now = now or datetime.now(timezone.utc)
        self._update_extremes(position, price, candle_1m)
        current_r = self.r_multiple(position, price)
        max_r = max(self._max_r.get(position.symbol, Decimal(0)), current_r)
        if (
            not c.enabled
            or not c.activate_after_partial_tp
            or not position.partial_tp_done
            or position.runner_mode_active
            or position.qty <= 0
            or max_r < Decimal(str(c.activate_min_r))
        ):
            return []

        strength, reason = self._runner_trend_strength(
            position,
            max_r=max_r,
            candle=candle_1m,
            snapshot_1m=snapshot_1m,
            snapshot_5m=snapshot_5m,
            volume_ratio=volume_ratio,
        )
        multiplier = self._runner_multiplier(strength)
        position.runner_mode_active = True
        position.runner_mode_started_at = now
        position.runner_trend_strength = strength
        position.runner_trailing_atr_multiplier = multiplier
        actions = [
            self._runner_event(
                position,
                "RUNNER_MODE_ACTIVATED",
                price=price,
                atr=atr,
                current_r=current_r,
                max_r=max_r,
                reason=reason or "PARTIAL_TP_FILLED",
            )
        ]
        trail_stop = self._trail_stop(position, atr, max_r)
        new_stop = self._ratchet(position, trail_stop)
        if new_stop is not None and self._runner_trailing_update_allowed(
            position, new_stop, atr, now
        ):
            old_stop = position.stop_loss_price
            position.stop_loss_price = new_stop
            self._record_runner_trailing_update(position, new_stop, now)
            actions.append(
                self._runner_event(
                    position,
                    "RUNNER_TRAILING_UPDATED",
                    price=price,
                    atr=atr,
                    current_r=current_r,
                    max_r=max_r,
                    old_stop=old_stop,
                    new_stop=new_stop,
                    reason="RUNNER_MODE_ACTIVATED",
                )
            )
            actions.append(PositionAction(type=PositionActionType.TRAIL_UPDATE, new_stop=new_stop))
        return actions

    def _runner_state_actions(
        self,
        position: Position,
        *,
        price: Decimal,
        atr: Decimal,
        candle: Candle | None,
        snapshot_1m: IndicatorSnapshot | None,
        snapshot_5m: IndicatorSnapshot | None,
        volume_ratio: Decimal | None,
        max_r: Decimal,
        current_r: Decimal,
        now: datetime,
    ) -> list[PositionAction]:
        if not position.runner_mode_active:
            return []
        strength, reason = self._runner_trend_strength(
            position,
            max_r=max_r,
            candle=candle,
            snapshot_1m=snapshot_1m,
            snapshot_5m=snapshot_5m,
            volume_ratio=volume_ratio,
        )
        old = position.runner_trend_strength
        if self._runner_weak_downgrade_pending(
            position, old=old, strength=strength, reason=reason, candle=candle
        ):
            return []
        if strength != "WEAK":
            self._clear_runner_weak_signal(position.symbol)
        position.runner_trend_strength = strength
        position.runner_trailing_atr_multiplier = self._runner_multiplier(strength)
        if old is None or old == strength:
            return []
        return [
            self._runner_event(
                position,
                "RUNNER_TREND_STRENGTH_CHANGED",
                price=price,
                atr=atr,
                current_r=current_r,
                max_r=max_r,
                reason=reason or f"{old}_TO_{strength}",
            )
        ]

    def _runner_weak_downgrade_pending(
        self,
        position: Position,
        *,
        old: str | None,
        strength: str,
        reason: str | None,
        candle: Candle | None,
    ) -> bool:
        if old not in {"STRONG", "VERY_STRONG"} or strength != "WEAK":
            return False

        c = self.cfg.position.runner_mode
        if reason == "STRONG_OPPOSITE_CANDLE":
            required = max(1, int(c.tighten_on_strong_opposite_candle_bars))
        elif reason == "ONE_MIN_EMA20_BREAK":
            required = max(1, int(c.tighten_on_1m_ema20_break_bars))
        elif reason == "FIVE_MIN_EMA20_BREAK":
            self._clear_runner_weak_signal(position.symbol)
            return False
        else:
            required = max(1, int(c.tighten_on_1m_ema20_break_bars))
        if required <= 1:
            return False

        symbol = position.symbol
        open_time = candle.open_time_ms if candle is not None else None
        if open_time is not None and open_time > 0:
            last_open_time = self._runner_weak_signal_open_times.get(symbol)
            if last_open_time != open_time:
                self._runner_weak_signal_open_times[symbol] = open_time
                self._runner_weak_signal_counts[symbol] = (
                    self._runner_weak_signal_counts.get(symbol, 0) + 1
                )
        else:
            self._runner_weak_signal_counts[symbol] = (
                self._runner_weak_signal_counts.get(symbol, 0) + 1
            )

        if self._runner_weak_signal_counts.get(symbol, 0) < required:
            return True
        self._clear_runner_weak_signal(symbol)
        return False

    def _clear_runner_weak_signal(self, symbol: str) -> None:
        self._runner_weak_signal_counts.pop(symbol, None)
        self._runner_weak_signal_open_times.pop(symbol, None)

    def _runner_trend_strength(
        self,
        position: Position,
        *,
        max_r: Decimal,
        candle: Candle | None,
        snapshot_1m: IndicatorSnapshot | None,
        snapshot_5m: IndicatorSnapshot | None,
        volume_ratio: Decimal | None,
    ) -> tuple[str, str | None]:
        weak_reason = self._runner_weakening_reason(
            position, candle, snapshot_1m, snapshot_5m, volume_ratio
        )
        if weak_reason is not None:
            return "WEAK", weak_reason

        c = self.cfg.position.runner_mode
        strong_min_r = Decimal(str(c.strong_trend_min_r))
        very_min_r = Decimal(str(c.very_strong_trend_min_r))
        strong = max_r >= strong_min_r and self._runner_trend_holds(
            position, snapshot_1m, snapshot_5m
        )
        if not strong:
            return "WEAK", "TREND_HOLD_WEAK"

        rsi = snapshot_1m.rsi14 if snapshot_1m is not None else None
        very = max_r >= very_min_r
        if position.side == PositionSide.LONG:
            very = very and rsi is not None and rsi >= Decimal(
                str(c.long_min_1m_rsi + 5)
            )
        else:
            very = very and rsi is not None and rsi <= Decimal(
                str(c.short_max_1m_rsi - 5)
            )
        if very:
            return "VERY_STRONG", "VERY_STRONG_TREND_HOLD"
        return "STRONG", "STRONG_TREND_HOLD"

    def _runner_trend_holds(
        self,
        position: Position,
        snapshot_1m: IndicatorSnapshot | None,
        snapshot_5m: IndicatorSnapshot | None,
    ) -> bool:
        c = self.cfg.position.runner_mode
        long = position.side == PositionSide.LONG
        if c.require_5m_trend_hold:
            if snapshot_5m is None or snapshot_5m.ema20 is None:
                return False
            if long and snapshot_5m.close <= snapshot_5m.ema20:
                return False
            if not long and snapshot_5m.close >= snapshot_5m.ema20:
                return False
        if c.require_1m_ema20_hold:
            if snapshot_1m is None or snapshot_1m.ema20 is None:
                return False
            if long and snapshot_1m.close <= snapshot_1m.ema20:
                return False
            if not long and snapshot_1m.close >= snapshot_1m.ema20:
                return False
        if snapshot_1m is None or snapshot_1m.rsi14 is None:
            return False
        if long:
            return snapshot_1m.rsi14 >= Decimal(str(c.long_min_1m_rsi))
        return snapshot_1m.rsi14 <= Decimal(str(c.short_max_1m_rsi))

    def _runner_weakening_reason(
        self,
        position: Position,
        candle: Candle | None,
        snapshot_1m: IndicatorSnapshot | None,
        snapshot_5m: IndicatorSnapshot | None,
        volume_ratio: Decimal | None,
    ) -> str | None:
        c = self.cfg.position.runner_mode
        long = position.side == PositionSide.LONG
        if snapshot_5m is not None and snapshot_5m.ema20 is not None:
            if long and snapshot_5m.close < snapshot_5m.ema20:
                return "FIVE_MIN_EMA20_BREAK"
            if not long and snapshot_5m.close > snapshot_5m.ema20:
                return "FIVE_MIN_EMA20_BREAK"
        if candle is not None and snapshot_1m is not None and snapshot_1m.ema20 is not None:
            against = (
                candle.close < snapshot_1m.ema20
                if long
                else candle.close > snapshot_1m.ema20
            )
            if against:
                count = self._runner_ema_break_counts.get(position.symbol, 0) + 1
                self._runner_ema_break_counts[position.symbol] = count
                if count >= c.tighten_on_1m_ema20_break_bars:
                    return "ONE_MIN_EMA20_BREAK"
            else:
                self._runner_ema_break_counts[position.symbol] = 0
        if (
            c.tighten_on_strong_opposite_candle
            and candle is not None
            and self._runner_strong_opposite_candle(position, candle, volume_ratio)
        ):
            return "STRONG_OPPOSITE_CANDLE"
        return None

    def _runner_strong_opposite_candle(
        self,
        position: Position,
        candle: Candle,
        volume_ratio: Decimal | None,
    ) -> bool:
        if volume_ratio is None:
            return False
        m = metrics_of(candle)
        if (
            not m.valid
            or m.body_ratio < Decimal("0.55")
            or volume_ratio < Decimal("1.5")
        ):
            return False
        if position.side == PositionSide.LONG:
            return (
                candle.close < candle.open
                and m.close_position_in_range <= Decimal("0.25")
            )
        return (
            candle.close > candle.open
            and m.close_position_in_range >= Decimal("0.75")
        )

    def _runner_multiplier(self, trend_strength: str) -> Decimal:
        c = self.cfg.position.runner_mode
        if trend_strength == "VERY_STRONG":
            return Decimal(str(c.very_strong_trend_trailing_atr))
        if trend_strength == "STRONG":
            return Decimal(str(c.strong_trend_trailing_atr))
        return Decimal(str(c.weak_trend_trailing_atr))

    def _runner_trailing_update_allowed(
        self,
        position: Position,
        new_stop: Decimal,
        atr: Decimal,
        now: datetime,
    ) -> bool:
        if not position.runner_mode_active:
            return True
        last_at = position.last_runner_trailing_update_at
        c = self.cfg.position.runner_mode
        if last_at is not None:
            elapsed = (now - last_at).total_seconds()
            if elapsed < c.min_trailing_update_interval_sec:
                return False
        last_stop = position.last_runner_trailing_stop or position.stop_loss_price
        if last_stop is None or atr <= 0:
            return True
        improvement = (
            new_stop - last_stop
            if position.side == PositionSide.LONG
            else last_stop - new_stop
        )
        return improvement >= atr * Decimal(str(c.min_trailing_improvement_atr))

    def _record_runner_trailing_update(
        self, position: Position, new_stop: Decimal, now: datetime
    ) -> None:
        if not position.runner_mode_active:
            return
        position.last_runner_trailing_update_at = now
        position.last_runner_trailing_stop = new_stop

    def _runner_event(
        self,
        position: Position,
        event_type: str,
        *,
        price: Decimal,
        atr: Decimal,
        current_r: Decimal,
        max_r: Decimal,
        old_stop: Decimal | None = None,
        new_stop: Decimal | None = None,
        reason: str | None = None,
    ) -> PositionAction:
        return PositionAction(
            type=PositionActionType.SCOUT_EVENT,
            event_type=event_type,
            data={
                "symbol": position.symbol,
                "side": position.side.value,
                "entry_price": str(position.avg_entry_price),
                "current_price": str(price),
                "remaining_qty": str(position.qty),
                "max_r": str(max_r),
                "current_r": str(current_r),
                "trend_strength": position.runner_trend_strength,
                "trailing_multiplier": str(position.runner_trailing_atr_multiplier)
                if position.runner_trailing_atr_multiplier is not None
                else None,
                "atr": str(atr),
                "highest_price": str(position.highest_price)
                if position.highest_price is not None
                else None,
                "lowest_price": str(position.lowest_price)
                if position.lowest_price is not None
                else None,
                "old_trailing_stop": str(old_stop) if old_stop is not None else None,
                "new_trailing_stop": str(new_stop) if new_stop is not None else None,
                "exchange_sl_before": str(old_stop) if old_stop is not None else None,
                "exchange_sl_after": str(new_stop) if new_stop is not None else None,
                "reason": reason,
            },
        )

    # ------------------------------------------------------------------ #
    # PRE_BREAKOUT_SCOUT management
    # ------------------------------------------------------------------ #
    def _scout_management_action(
        self,
        position: Position,
        *,
        price: Decimal,
        atr: Decimal,
        candle: Candle | None,
        snapshot_1m: IndicatorSnapshot | None,
        volume_ratio: Decimal | None,
        max_r: Decimal,
        now: datetime,
    ) -> tuple[list[PositionAction], bool]:
        c = self.cfg.position.scout_management
        if (
            not c.enabled
            or position.entry_mode != EntryMode.PRE_BREAKOUT_SCOUT
            or position.scout_state == ScoutState.NONE
        ):
            return [], True
        if position.scout_state == ScoutState.ACTIVE_TREND:
            return [], True
        if candle is None or atr <= 0:
            return [], False

        if position.scout_state == ScoutState.SCOUT_CONFIRMED:
            if c.convert_to_active_on_confirmation:
                position.scout_state = ScoutState.ACTIVE_TREND
                return [
                    self._scout_event(
                        position,
                        "SCOUT_ACTIVATED",
                        price,
                        candle,
                        snapshot_1m=snapshot_1m,
                        volume_ratio=volume_ratio,
                        atr=atr,
                    )
                ], True
            return [], False

        if position.scout_state not in {
            ScoutState.SCOUT_PENDING,
            ScoutState.SCOUT_WARNING,
        }:
            return [], True

        if self._scout_confirmed(position, atr, candle, volume_ratio):
            self._clear_scout_warning(position)
            position.scout_state = ScoutState.SCOUT_CONFIRMED
            position.scout_confirmed_at = now
            events = [
                self._scout_event(
                    position,
                    "SCOUT_CONFIRMED",
                    price,
                    candle,
                    snapshot_1m=snapshot_1m,
                    volume_ratio=volume_ratio,
                    atr=atr,
                )
            ]
            if c.convert_to_active_on_confirmation:
                position.scout_state = ScoutState.ACTIVE_TREND
                events.append(
                    self._scout_event(
                        position,
                        "SCOUT_ACTIVATED",
                        price,
                        candle,
                        snapshot_1m=snapshot_1m,
                        volume_ratio=volume_ratio,
                        atr=atr,
                    )
                )
                return events, True
            return events, False

        bars_since_scout = self._scout_bars_since_entry(position)
        catastrophic_reason = self._scout_catastrophic_opposite_reason(
            position, candle, volume_ratio, atr
        )
        if (
            catastrophic_reason is not None
            and position.scout_defensive_reduction_count
            < c.max_defensive_reductions
        ):
            return [
                self._scout_reduce_action(
                    position,
                    price,
                    candle,
                    snapshot_1m=snapshot_1m,
                    volume_ratio=volume_ratio,
                    atr=atr,
                    reason=catastrophic_reason,
                    exit_reason=ExitReason.SCOUT_CATASTROPHIC_REDUCE,
                    event_type="SCOUT_CATASTROPHIC_REDUCE",
                )
            ], False

        if position.scout_state == ScoutState.SCOUT_WARNING:
            if self._scout_warning_recovered(position, candle, snapshot_1m):
                event = self._scout_event(
                    position,
                    "SCOUT_WARNING_RECOVERED",
                    price,
                    candle,
                    snapshot_1m=snapshot_1m,
                    volume_ratio=volume_ratio,
                    atr=atr,
                    reason=position.scout_warning_reason
                    or "SCOUT_WARNING_RECOVERED",
                )
                self._clear_scout_warning(position)
                position.scout_state = ScoutState.SCOUT_PENDING
                return [event], False

            if self._scout_warning_bars(position) < c.warning_confirm_bars:
                return [], False
            if bars_since_scout < c.min_hold_bars_before_defensive_reduce:
                return [], False
            if (
                position.scout_defensive_reduction_count
                < c.max_defensive_reductions
            ):
                return [
                    self._scout_reduce_action(
                        position,
                        price,
                        candle,
                        snapshot_1m=snapshot_1m,
                        volume_ratio=volume_ratio,
                        atr=atr,
                        reason=position.scout_warning_reason
                        or "SCOUT_WARNING_NOT_RECOVERED",
                        exit_reason=ExitReason.SCOUT_DEFENSIVE_REDUCE,
                        event_type="SCOUT_DEFENSIVE_REDUCE",
                    )
                ], False
            self._clear_scout_warning(position)
            position.scout_state = ScoutState.SCOUT_PENDING

        strong_reason = self._scout_strong_opposite_reason(
            position, candle, volume_ratio
        )
        if (
            strong_reason is not None
            and position.scout_defensive_reduction_count
            < c.max_defensive_reductions
        ):
            position.scout_state = ScoutState.SCOUT_WARNING
            position.scout_warning_started_at_bar = bars_since_scout
            position.scout_warning_reason = strong_reason
            return [
                self._scout_event(
                    position,
                    "SCOUT_WARNING_STARTED",
                    price,
                    candle,
                    snapshot_1m=snapshot_1m,
                    volume_ratio=volume_ratio,
                    atr=atr,
                    reason=strong_reason,
                )
            ], False

        in_grace = bars_since_scout < c.grace_bars
        weakness_reason = (
            None
            if in_grace
            else self._scout_weakness_reason(
                position, candle, snapshot_1m, volume_ratio
            )
        )

        if (
            weakness_reason is not None
            and position.scout_defensive_reduction_count
            < c.max_defensive_reductions
        ):
            return [
                self._scout_reduce_action(
                    position,
                    price,
                    candle,
                    snapshot_1m=snapshot_1m,
                    volume_ratio=volume_ratio,
                    atr=atr,
                    reason=weakness_reason,
                    exit_reason=ExitReason.SCOUT_DEFENSIVE_REDUCE,
                    event_type="SCOUT_DEFENSIVE_REDUCE",
                )
            ], False

        stagnation = self._stagnation_action(
            position,
            max_r,
            current_r=self.r_multiple(position, price),
            price=price,
            atr=atr,
        )
        if stagnation is not None:
            if stagnation.event_type == "STAGNATION_DELAYED_BY_ENTRY_MODE":
                return [stagnation], False
            return [
                self._scout_event(
                    position, "SCOUT_INVALIDATED", price, candle,
                    snapshot_1m=snapshot_1m,
                    volume_ratio=volume_ratio,
                    atr=atr,
                    reason=stagnation.reason.value if stagnation.reason else "STAGNATION",
                ),
                stagnation,
            ], False
        return [], False

    def _scout_confirmed(
        self,
        position: Position,
        atr: Decimal,
        candle: Candle,
        volume_ratio: Decimal | None,
    ) -> bool:
        c = self.cfg.position.scout_management
        if volume_ratio is None or volume_ratio < Decimal(str(c.confirmation_volume_ratio)):
            return False
        m = metrics_of(candle)
        if not m.valid:
            return False
        boundary = atr * Decimal(str(c.confirmation_boundary_atr))
        if position.side == PositionSide.LONG and position.scout_entry_box_high is not None:
            return (
                candle.close > position.scout_entry_box_high + boundary
                and m.close_position_in_range >= Decimal("0.65")
            )
        if position.side == PositionSide.SHORT and position.scout_entry_box_low is not None:
            return (
                candle.close < position.scout_entry_box_low - boundary
                and m.close_position_in_range <= Decimal("0.35")
            )
        return False

    def _scout_weakness_reason(
        self,
        position: Position,
        candle: Candle,
        snapshot_1m: IndicatorSnapshot | None,
        volume_ratio: Decimal | None,
    ) -> str | None:
        c = self.cfg.position.scout_management
        if (
            c.invalidate_on_box_mid_reclaim
            and position.scout_entry_box_mid is not None
        ):
            if position.side == PositionSide.LONG and candle.close < position.scout_entry_box_mid:
                return "BOX_MID_RECLAIMED_AGAINST_LONG"
            if position.side == PositionSide.SHORT and candle.close > position.scout_entry_box_mid:
                return "BOX_MID_RECLAIMED_AGAINST_SHORT"

        ema_reason = self._scout_ema_reclaim_reason(position, candle, snapshot_1m)
        if ema_reason is not None:
            return ema_reason

        if snapshot_1m is not None and snapshot_1m.rsi14 is not None:
            if (
                position.side == PositionSide.LONG
                and snapshot_1m.rsi14 <= Decimal(str(c.long_invalid_rsi_threshold))
            ):
                return "RSI_WEAK_FOR_LONG_SCOUT"
            if (
                position.side == PositionSide.SHORT
                and snapshot_1m.rsi14 >= Decimal(str(c.short_invalid_rsi_threshold))
            ):
                return "RSI_WEAK_FOR_SHORT_SCOUT"

        return self._scout_strong_opposite_reason(position, candle, volume_ratio)

    def _scout_ema_reclaim_reason(
        self,
        position: Position,
        candle: Candle,
        snapshot_1m: IndicatorSnapshot | None,
    ) -> str | None:
        c = self.cfg.position.scout_management
        if snapshot_1m is None or snapshot_1m.ema20 is None:
            return None
        against = (
            candle.close < snapshot_1m.ema20
            if position.side == PositionSide.LONG
            else candle.close > snapshot_1m.ema20
        )
        key = position.symbol
        if against:
            count = self._scout_ema_reclaim_counts.get(key, 0) + 1
            self._scout_ema_reclaim_counts[key] = count
            if count >= c.invalidate_on_ema20_reclaim_bars:
                return "EMA20_RECLAIMED_AGAINST_SCOUT"
        else:
            self._scout_ema_reclaim_counts[key] = 0
        return None

    def _scout_strong_opposite_reason(
        self,
        position: Position,
        candle: Candle,
        volume_ratio: Decimal | None,
    ) -> str | None:
        if volume_ratio is None:
            return None
        c = self.cfg.position.scout_management
        m = metrics_of(candle)
        if not m.valid:
            return None
        if (
            m.body_ratio < Decimal(str(c.strong_opposite_candle_body_ratio))
            or volume_ratio < Decimal(str(c.strong_opposite_candle_volume_ratio))
        ):
            return None
        if (
            position.side == PositionSide.LONG
            and candle.close < candle.open
            and m.close_position_in_range <= Decimal("0.25")
        ):
            return "STRONG_BEARISH_CANDLE"
        if (
            position.side == PositionSide.SHORT
            and candle.close > candle.open
            and m.close_position_in_range >= Decimal("0.75")
        ):
            return "STRONG_BULLISH_CANDLE"
        return None

    def _scout_catastrophic_opposite_reason(
        self,
        position: Position,
        candle: Candle,
        volume_ratio: Decimal | None,
        atr: Decimal,
    ) -> str | None:
        if volume_ratio is None or atr <= 0:
            return None
        c = self.cfg.position.scout_management
        m = metrics_of(candle)
        if not m.valid:
            return None
        opposite_move_atr = self._scout_opposite_move_atr(position, candle, atr)
        if (
            opposite_move_atr is None
            or m.body_ratio < Decimal(str(c.catastrophic_opposite_candle_body_ratio))
            or volume_ratio < Decimal(str(c.catastrophic_opposite_candle_volume_ratio))
            or opposite_move_atr < Decimal(str(c.catastrophic_opposite_move_atr))
        ):
            return None
        if (
            position.side == PositionSide.LONG
            and candle.close < candle.open
            and m.close_position_in_range <= Decimal("0.20")
        ):
            return "CATASTROPHIC_BEARISH_CANDLE"
        if (
            position.side == PositionSide.SHORT
            and candle.close > candle.open
            and m.close_position_in_range >= Decimal("0.80")
        ):
            return "CATASTROPHIC_BULLISH_CANDLE"
        return None

    def _scout_warning_recovered(
        self,
        position: Position,
        candle: Candle,
        snapshot_1m: IndicatorSnapshot | None,
    ) -> bool:
        m = metrics_of(candle)
        if not m.valid:
            return False
        ema20 = snapshot_1m.ema20 if snapshot_1m is not None else None
        if position.side == PositionSide.LONG:
            return (
                candle.close >= position.avg_entry_price
                or (ema20 is not None and candle.close >= ema20)
                or m.close_position_in_range >= Decimal("0.50")
            )
        return (
            candle.close <= position.avg_entry_price
            or (ema20 is not None and candle.close <= ema20)
            or m.close_position_in_range <= Decimal("0.50")
        )

    def _scout_bars_since_entry(self, position: Position) -> int:
        start = position.scout_entry_bar_index
        if start is None:
            return position.bars_since_entry
        return max(0, position.bars_since_entry - start)

    def _scout_warning_bars(self, position: Position) -> int:
        started = position.scout_warning_started_at_bar
        if started is None:
            return 0
        return max(0, self._scout_bars_since_entry(position) - started)

    @staticmethod
    def _clear_scout_warning(position: Position) -> None:
        position.scout_warning_started_at_bar = None
        position.scout_warning_reason = None

    def _scout_reduce_action(
        self,
        position: Position,
        price: Decimal,
        candle: Candle,
        *,
        snapshot_1m: IndicatorSnapshot | None,
        volume_ratio: Decimal | None,
        atr: Decimal,
        reason: str,
        exit_reason: ExitReason,
        event_type: str,
    ) -> PositionAction:
        c = self.cfg.position.scout_management
        position.scout_defensive_reduction_count += 1
        qty = self._round_qty(
            position.qty * Decimal(str(c.defensive_reduce_fraction))
        )
        data = self._scout_event_data(
            position,
            price,
            candle,
            snapshot_1m=snapshot_1m,
            volume_ratio=volume_ratio,
            atr=atr,
            reason=reason,
        )
        self._clear_scout_warning(position)
        position.scout_state = ScoutState.SCOUT_PENDING
        data["scout_state"] = position.scout_state.value
        return PositionAction(
            type=PositionActionType.REDUCE,
            qty=qty,
            reason=exit_reason,
            event_type=event_type,
            data=data,
        )

    def _scout_opposite_move_atr(
        self,
        position: Position,
        candle: Candle,
        atr: Decimal | None,
    ) -> Decimal | None:
        if atr is None or atr <= 0:
            return None
        if position.side == PositionSide.LONG and candle.close < candle.open:
            return (candle.open - candle.close) / atr
        if position.side == PositionSide.SHORT and candle.close > candle.open:
            return (candle.close - candle.open) / atr
        return Decimal(0)

    def _scout_event(
        self,
        position: Position,
        event_type: str,
        price: Decimal,
        candle: Candle,
        *,
        snapshot_1m: IndicatorSnapshot | None = None,
        volume_ratio: Decimal | None = None,
        atr: Decimal | None = None,
        reason: str | None = None,
    ) -> PositionAction:
        return PositionAction(
            type=PositionActionType.SCOUT_EVENT,
            event_type=event_type,
            data=self._scout_event_data(
                position,
                price,
                candle,
                snapshot_1m=snapshot_1m,
                volume_ratio=volume_ratio,
                atr=atr,
                reason=reason,
            ),
        )

    def _scout_event_data(
        self,
        position: Position,
        price: Decimal,
        candle: Candle,
        *,
        snapshot_1m: IndicatorSnapshot | None = None,
        volume_ratio: Decimal | None = None,
        atr: Decimal | None = None,
        reason: str | None = None,
    ) -> dict:
        m = metrics_of(candle)
        opposite_move_atr = self._scout_opposite_move_atr(position, candle, atr)
        return {
            "symbol": position.symbol,
            "side": position.side.value,
            "entry_price": str(position.avg_entry_price),
            "current_price": str(price),
            "scout_state": position.scout_state.value,
            "bars_since_entry": self._scout_bars_since_entry(position),
            "warning_bars": self._scout_warning_bars(position),
            "box_high": str(position.scout_entry_box_high)
            if position.scout_entry_box_high is not None
            else None,
            "box_low": str(position.scout_entry_box_low)
            if position.scout_entry_box_low is not None
            else None,
            "box_mid": str(position.scout_entry_box_mid)
            if position.scout_entry_box_mid is not None
            else None,
            "scout_entry_level": str(position.scout_entry_level)
            if position.scout_entry_level is not None
            else None,
            "scout_defensive_reduction_count": position.scout_defensive_reduction_count,
            "reason": reason,
            "rsi14": str(snapshot_1m.rsi14)
            if snapshot_1m is not None and snapshot_1m.rsi14 is not None
            else None,
            "ema20": str(snapshot_1m.ema20)
            if snapshot_1m is not None and snapshot_1m.ema20 is not None
            else None,
            "volume_ratio": str(volume_ratio) if volume_ratio is not None else None,
            "body_ratio": str(m.body_ratio) if m.valid else None,
            "close_position_in_range": str(m.close_position_in_range)
            if m.valid
            else None,
            "opposite_move_atr": str(opposite_move_atr)
            if opposite_move_atr is not None
            else None,
        }

    # ------------------------------------------------------------------ #
    def _update_extremes(
        self, position: Position, price: Decimal, candle: Candle | None
    ) -> None:
        high = candle.high if candle is not None else price
        low = candle.low if candle is not None else price
        position.highest_price = (
            high if position.highest_price is None else max(position.highest_price, high)
        )
        position.lowest_price = (
            low if position.lowest_price is None else min(position.lowest_price, low)
        )

    def _trail_stop(self, position: Position, atr: Decimal, max_r: Decimal) -> Decimal:
        if (
            position.runner_mode_active
            and position.runner_trailing_atr_multiplier is not None
        ):
            mult = position.runner_trailing_atr_multiplier
        else:
            mult = (
                self.trailing_ext_mult
                if max_r >= self.trailing_ext_after_r
                else self.trailing_mult
            )
        if position.side == PositionSide.LONG:
            anchor = position.highest_price or position.avg_entry_price
            return anchor - atr * mult
        anchor = position.lowest_price or position.avg_entry_price
        return anchor + atr * mult

    def _stop_breached(
        self, position: Position, price: Decimal, stop: Decimal
    ) -> bool:
        if position.side == PositionSide.LONG:
            return price <= stop
        return price >= stop

    def _effective_stop(self, position: Position, trail_stop: Decimal) -> Decimal:
        """Use the more protective stop when dynamic trailing would be looser."""
        cur = position.stop_loss_price
        if cur is None:
            return trail_stop
        if position.side == PositionSide.LONG:
            return max(cur, trail_stop)
        return min(cur, trail_stop)

    def _ratchet(self, position: Position, trail_stop: Decimal) -> Decimal | None:
        """Move the stop in the favourable direction only."""
        cur = position.stop_loss_price
        if position.side == PositionSide.LONG:
            if cur is None or trail_stop > cur:
                return trail_stop
        else:
            if cur is None or trail_stop < cur:
                return trail_stop
        return None

    def _management_event_data(
        self,
        position: Position,
        *,
        price: Decimal,
        atr: Decimal,
        r: Decimal,
        candle: Candle | None,
        snapshot_5m: IndicatorSnapshot | None,
        volume_ratio: Decimal | None,
        reason: str,
    ) -> dict:
        body_ratio = None
        close_position = None
        if candle is not None:
            m = metrics_of(candle)
            if m.valid:
                body_ratio = str(m.body_ratio)
                close_position = str(m.close_position_in_range)
        return {
            "symbol": position.symbol,
            "side": position.side.value,
            "entry_price": str(position.avg_entry_price),
            "current_price": str(price),
            "entry_mode": position.entry_mode.value if position.entry_mode else None,
            "qty": str(position.qty),
            "current_r": str(r),
            "bars_since_entry": position.bars_since_entry,
            "atr": str(atr),
            "volume_ratio": str(volume_ratio) if volume_ratio is not None else None,
            "candle_close": str(candle.close) if candle is not None else None,
            "body_ratio": body_ratio,
            "close_position_in_range": close_position,
            "snapshot_5m_close": str(snapshot_5m.close)
            if snapshot_5m is not None
            else None,
            "snapshot_5m_ema20": str(snapshot_5m.ema20)
            if snapshot_5m is not None and snapshot_5m.ema20 is not None
            else None,
            "reason": reason,
        }

    def _scenario_action(
        self,
        position: Position,
        r: Decimal,
        snapshot_5m: IndicatorSnapshot | None,
        candle: Candle | None,
        volume_ratio: Decimal | None,
        *,
        price: Decimal,
        atr: Decimal,
    ) -> PositionAction | None:
        # Already in the post-invalidation recovery window?
        if position.symbol in self._scenario_recovery:
            left = self._scenario_recovery[position.symbol] - 1
            if r >= Decimal("0.5"):
                del self._scenario_recovery[position.symbol]  # recovered
                return None
            if left <= 0:
                del self._scenario_recovery[position.symbol]
                return self._exit(position, ExitReason.SCENARIO_INVALID)
            self._scenario_recovery[position.symbol] = left
            return None

        if self._scenario_invalid(position, snapshot_5m, candle, volume_ratio):
            scenario_key = self._position_scenario_key(position)
            if scenario_key in self._scenario_reduced:
                if r < Decimal("0.5"):
                    self._scenario_recovery[position.symbol] = 3
                return None
            grace = self._scenario_invalid_grace_bars(position)
            if grace > 0 and position.bars_since_entry <= grace:
                return PositionAction(
                    type=PositionActionType.SCOUT_EVENT,
                    event_type="STAGNATION_DELAYED_BY_ENTRY_MODE",
                    data=self._management_event_data(
                        position,
                        price=price,
                        atr=atr,
                        r=r,
                        candle=candle,
                        snapshot_5m=snapshot_5m,
                        volume_ratio=volume_ratio,
                        reason="RETEST_SCENARIO_INVALID_GRACE",
                    ),
                )
            if self._mild_retest_break_level_invalid(
                position, r, snapshot_5m, candle, volume_ratio
            ):
                tighten_bars = self.cfg.stagnation_exit.retest_confirm.tighten_after_bars
                if position.bars_since_entry < tighten_bars:
                    return PositionAction(
                        type=PositionActionType.SCOUT_EVENT,
                        event_type="STAGNATION_DELAYED_BY_ENTRY_MODE",
                        data=self._management_event_data(
                            position,
                            price=price,
                            atr=atr,
                            r=r,
                            candle=candle,
                            snapshot_5m=snapshot_5m,
                            volume_ratio=volume_ratio,
                            reason="RETEST_BREAK_LEVEL_INVALID_DELAYED",
                        ),
                    )
                return None
            if not self._scout_scenario_invalid_confirmed(position, candle):
                return PositionAction(
                    type=PositionActionType.SCOUT_EVENT,
                    event_type="STAGNATION_DELAYED_BY_ENTRY_MODE",
                    data=self._management_event_data(
                        position,
                        price=price,
                        atr=atr,
                        r=r,
                        candle=candle,
                        snapshot_5m=snapshot_5m,
                        volume_ratio=volume_ratio,
                        reason="SCOUT_SCENARIO_INVALID_CONFIRMING",
                    ),
                )
            # reduce 50% and open a 3-bar recovery window (impl doc §14.5)
            self._scenario_recovery[position.symbol] = 3
            self._scenario_reduced.add(scenario_key)
            return PositionAction(
                type=PositionActionType.REDUCE,
                qty=self._round_qty(position.qty * Decimal("0.5")),
                reason=ExitReason.SCENARIO_INVALID,
                event_type="SCENARIO_INVALID_REDUCE",
                data=self._management_event_data(
                    position,
                    price=price,
                    atr=atr,
                    r=r,
                    candle=candle,
                    snapshot_5m=snapshot_5m,
                    volume_ratio=volume_ratio,
                    reason="SCENARIO_INVALID",
                ),
            )
        self._clear_scout_scenario_invalid(position)
        return None

    @staticmethod
    def _position_scenario_key(position: Position) -> tuple[str, str]:
        return (position.symbol, position.opened_at.isoformat())

    def _scenario_invalid_grace_bars(self, position: Position) -> int:
        if position.entry_mode != EntryMode.RETEST_CONFIRM:
            return 0
        return max(0, int(self.cfg.stagnation_exit.retest_confirm.scenario_invalid_grace_bars))

    def _mild_retest_break_level_invalid(
        self,
        position: Position,
        r: Decimal,
        snapshot_5m: IndicatorSnapshot | None,
        candle: Candle | None,
        volume_ratio: Decimal | None,
    ) -> bool:
        if position.entry_mode != EntryMode.RETEST_CONFIRM:
            return False
        if r <= Decimal("-0.5"):
            return False
        return not self._hard_scenario_invalid(
            position, snapshot_5m, candle, volume_ratio
        )

    def _hard_scenario_invalid(
        self,
        position: Position,
        snapshot_5m: IndicatorSnapshot | None,
        candle: Candle | None,
        volume_ratio: Decimal | None,
    ) -> bool:
        long = position.side == PositionSide.LONG
        if snapshot_5m is not None and snapshot_5m.ema20 is not None:
            if long and snapshot_5m.close < snapshot_5m.ema20:
                return True
            if not long and snapshot_5m.close > snapshot_5m.ema20:
                return True
        if candle is None or volume_ratio is None:
            return False
        m = metrics_of(candle)
        if not m.valid:
            return False
        if m.body_ratio < Decimal("0.55") or volume_ratio < Decimal("1.5"):
            return False
        if long:
            return (
                candle.close < candle.open
                and m.close_position_in_range <= Decimal("0.25")
            )
        return (
            candle.close > candle.open
            and m.close_position_in_range >= Decimal("0.75")
        )

    def _scout_scenario_invalid_confirmed(
        self, position: Position, candle: Candle | None
    ) -> bool:
        if position.entry_mode != EntryMode.PRE_BREAKOUT_SCOUT:
            return True

        key = self._position_scenario_key(position)
        if self._break_level_invalid_confirmed(position, candle, key):
            self._scout_scenario_invalid_closes.pop(key, None)
            return True

        open_time = (
            candle.open_time_ms
            if candle is not None and candle.open_time_ms > 0
            else None
        )
        last_open_time, prev_count = self._scout_scenario_invalid_closes.get(
            key, (None, 0)
        )
        if open_time is not None and open_time == last_open_time:
            return prev_count >= 2

        count = prev_count + 1
        self._scout_scenario_invalid_closes[key] = (open_time, count)
        return count >= 2

    def _break_level_invalid_confirmed(
        self, position: Position, candle: Candle | None, key: tuple[str, str]
    ) -> bool:
        if position.breakout_level is None or candle is None:
            return False
        wrong_side = (
            candle.close < position.breakout_level
            if position.side == PositionSide.LONG
            else candle.close > position.breakout_level
        )
        if not wrong_side:
            return False
        _, count = self._break_level_fail_closes.get(key, (None, 0))
        return count >= 2

    def _clear_scout_scenario_invalid(self, position: Position) -> None:
        if position.entry_mode == EntryMode.PRE_BREAKOUT_SCOUT:
            self._scout_scenario_invalid_closes.pop(
                self._position_scenario_key(position), None
            )

    def _scenario_invalid(
        self,
        position: Position,
        snapshot_5m: IndicatorSnapshot | None,
        candle: Candle | None,
        volume_ratio: Decimal | None,
        *,
        include_counter_candle: bool = True,
    ) -> bool:
        long = position.side == PositionSide.LONG
        # 5m close vs 5m EMA20
        if snapshot_5m is not None and snapshot_5m.ema20 is not None:
            if long and snapshot_5m.close < snapshot_5m.ema20:
                return True
            if not long and snapshot_5m.close > snapshot_5m.ema20:
                return True
        if candle is not None and self._break_level_invalid(position, candle):
            return True
        # strong counter-trend candle
        if include_counter_candle and candle is not None and volume_ratio is not None:
            m = metrics_of(candle)
            if m.valid and m.body_ratio >= Decimal("0.55") and volume_ratio >= Decimal("1.5"):
                if long and candle.close < candle.open and m.close_position_in_range <= Decimal("0.25"):
                    return True
                if not long and candle.close > candle.open and m.close_position_in_range >= Decimal("0.75"):
                    return True
        return False

    def _break_level_invalid(self, position: Position, candle: Candle) -> bool:
        """2 consecutive 1m closes beyond the breakout/breakdown level (§14.5)."""
        if position.breakout_level is None:
            return False
        key = self._position_scenario_key(position)
        open_time = candle.open_time_ms if candle.open_time_ms > 0 else None
        wrong_side = (
            candle.close < position.breakout_level
            if position.side == PositionSide.LONG
            else candle.close > position.breakout_level
        )
        if wrong_side:
            last_open_time, prev_count = self._break_level_fail_closes.get(key, (None, 0))
            if open_time is not None and open_time == last_open_time:
                return prev_count >= 2
            count = prev_count + 1
            self._break_level_fail_closes[key] = (open_time, count)
            return count >= 2
        self._break_level_fail_closes.pop(key, None)
        return False

    def _stagnation_action(
        self,
        position: Position,
        max_r: Decimal,
        *,
        current_r: Decimal,
        price: Decimal,
        atr: Decimal,
    ) -> PositionAction | None:
        if not self.cfg.stagnation_exit.enabled:
            return None
        bars = position.bars_since_entry
        mode = position.entry_mode
        se = self.cfg.stagnation_exit
        from packages.core.enums import EntryMode

        if mode == EntryMode.PRE_BREAKOUT_SCOUT:
            min_progress = Decimal(str(se.pre_breakout_scout.min_progress_r))
            if (
                bars >= se.pre_breakout_scout.max_bars_without_breakout
                and max_r < min_progress
            ):
                return self._exit(position, ExitReason.STAGNATION)
            if bars >= 8 and max_r < Decimal("0.5"):
                return self._stagnation_delay_event(
                    position,
                    current_r=current_r,
                    max_r=max_r,
                    price=price,
                    atr=atr,
                    reason="SCOUT_STAGNATION_DELAYED",
                )
        elif mode == EntryMode.BREAKOUT_CONFIRM:
            if bars >= se.breakout_confirm.max_bars_without_1r and max_r < Decimal("1.0"):
                return self._exit(position, ExitReason.STAGNATION)
            if (
                bars >= se.breakout_confirm.reduce_after_bars
                and max_r < Decimal("0.5")
                and position.symbol not in self._stag_reduced
            ):
                self._stag_reduced.add(position.symbol)
                return PositionAction(
                    type=PositionActionType.REDUCE,
                    qty=self._round_qty(position.qty * Decimal(str(se.breakout_confirm.reduce_fraction))),
                    reason=ExitReason.STAGNATION,
                    event_type="STAGNATION_REDUCE",
                    data={
                        "symbol": position.symbol,
                        "side": position.side.value,
                        "entry_price": str(position.avg_entry_price),
                        "entry_mode": mode.value if mode is not None else None,
                        "qty": str(position.qty),
                        "reduce_fraction": str(se.breakout_confirm.reduce_fraction),
                        "bars_since_entry": bars,
                        "max_r": str(max_r),
                        "reason": "STAGNATION",
                    },
                )
            if bars >= 10 and max_r < Decimal("1.0"):
                return self._stagnation_delay_event(
                    position,
                    current_r=current_r,
                    max_r=max_r,
                    price=price,
                    atr=atr,
                    reason="BREAKOUT_EXIT_DELAYED",
                )
            if (
                bars >= 5
                and max_r < Decimal("0.5")
                and position.symbol not in self._stag_reduced
            ):
                return self._stagnation_delay_event(
                    position,
                    current_r=current_r,
                    max_r=max_r,
                    price=price,
                    atr=atr,
                    reason="BREAKOUT_REDUCE_DELAYED",
                )
        elif mode == EntryMode.RETEST_CONFIRM:
            if bars >= se.retest_confirm.max_bars_without_1r and max_r < Decimal("1.0"):
                return self._exit(position, ExitReason.STAGNATION)
            if bars >= se.retest_confirm.tighten_after_bars and max_r < Decimal("0.5"):
                # tighten stop toward entry (impl doc §14.4 retest)
                tighter = self._tighten_stop(position)
                return PositionAction(type=PositionActionType.TRAIL_UPDATE, new_stop=tighter)
            if bars >= 12 and max_r < Decimal("1.0"):
                return self._stagnation_delay_event(
                    position,
                    current_r=current_r,
                    max_r=max_r,
                    price=price,
                    atr=atr,
                    reason="RETEST_EXIT_DELAYED",
                )
            if bars >= 6 and max_r < Decimal("0.5"):
                return self._stagnation_delay_event(
                    position,
                    current_r=current_r,
                    max_r=max_r,
                    price=price,
                    atr=atr,
                    reason="RETEST_TIGHTEN_DELAYED",
                )
        return None

    def _stagnation_delay_event(
        self,
        position: Position,
        *,
        current_r: Decimal,
        max_r: Decimal,
        price: Decimal,
        atr: Decimal,
        reason: str,
    ) -> PositionAction | None:
        key = (position.symbol, reason, position.opened_at.isoformat())
        if key in self._stagnation_delay_emitted:
            return None
        self._stagnation_delay_emitted.add(key)
        return PositionAction(
            type=PositionActionType.SCOUT_EVENT,
            event_type="STAGNATION_DELAYED_BY_ENTRY_MODE",
            data={
                "symbol": position.symbol,
                "side": position.side.value,
                "entry_mode": position.entry_mode.value
                if position.entry_mode is not None
                else None,
                "entry_price": str(position.avg_entry_price),
                "current_price": str(price),
                "remaining_qty": str(position.qty),
                "max_r": str(max_r),
                "current_r": str(current_r),
                "trend_strength": position.runner_trend_strength,
                "trailing_multiplier": str(position.runner_trailing_atr_multiplier)
                if position.runner_trailing_atr_multiplier is not None
                else None,
                "atr": str(atr),
                "highest_price": str(position.highest_price)
                if position.highest_price is not None
                else None,
                "lowest_price": str(position.lowest_price)
                if position.lowest_price is not None
                else None,
                "old_trailing_stop": str(position.stop_loss_price)
                if position.stop_loss_price is not None
                else None,
                "exchange_sl_before": str(position.stop_loss_price)
                if position.stop_loss_price is not None
                else None,
                "bars_since_entry": position.bars_since_entry,
                "reason": reason,
            },
        )

    def _tighten_stop(self, position: Position) -> Decimal:
        entry = position.avg_entry_price
        cur = position.stop_loss_price or entry
        # move halfway from current stop to entry
        return (cur + entry) / Decimal(2)

    def _exit(self, position: Position, reason: ExitReason) -> PositionAction:
        position.status = PositionStatus.CLOSING
        position.exit_reason = reason
        return PositionAction(type=PositionActionType.EXIT, qty=position.qty, reason=reason)

    def _round_qty(self, qty: Decimal) -> Decimal:
        return qty
