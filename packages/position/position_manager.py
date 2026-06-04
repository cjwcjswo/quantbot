"""PositionManager: bot position lifecycle management (impl doc §14, arch doc §6.21).

``evaluate`` is a pure, per-1m-bar decision function returning the actions to take
for one bot-managed position: partial take-profit (+2R 50%), trailing stop
(+2R ATR*2.0, +5R ATR*2.5), stagnation exit, scenario-invalidation exit and the
max-holding-time exit. Order execution (LIVE OrderManager / PAPER engine) is
applied by the caller, keeping this logic deterministic and unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from packages.config.settings import AppConfig
from packages.core.enums import ExitReason, PositionSide, PositionStatus
from packages.core.models import Candle, IndicatorSnapshot, Position
from packages.entry.candle_metrics import metrics_of


class PositionActionType(StrEnum):
    PARTIAL_TP = "PARTIAL_TP"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    TRAIL_UPDATE = "TRAIL_UPDATE"


@dataclass(frozen=True)
class PositionAction:
    type: PositionActionType
    qty: Decimal | None = None
    reason: ExitReason | None = None
    new_stop: Decimal | None = None


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
        self._break_level_fail_closes: dict[str, int] = {}

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
        snapshot_5m: IndicatorSnapshot | None = None,
        volume_ratio: Decimal | None = None,
        now: datetime | None = None,
    ) -> list[PositionAction]:
        if not position.is_bot_managed or position.status != PositionStatus.ACTIVE:
            return []

        now = now or datetime.now(timezone.utc)
        position.bars_since_entry += 1
        self._update_extremes(position, price, candle_1m)
        r = self.r_multiple(position, price)
        max_r = max(self._max_r.get(position.symbol, Decimal(0)), r)
        self._max_r[position.symbol] = max_r

        # 1. max holding time (§14, position.max_holding_minutes)
        held_min = (now - position.opened_at).total_seconds() / 60
        if held_min >= self.max_holding_minutes:
            return [self._exit(position, ExitReason.MAX_HOLDING_TIME)]

        # 2. trailing stop breach (§14.3)
        if max_r >= self.trailing_start_r:
            position.trailing_active = True
            trail_stop = self._trail_stop(position, atr, max_r)
            if self._stop_breached(position, price, trail_stop):
                return [self._exit(position, ExitReason.TRAILING_STOP)]

        # 3. scenario invalidation (§14.5)
        scenario = self._scenario_action(position, r, snapshot_5m, candle_1m, volume_ratio)
        if scenario is not None:
            return [scenario]

        # 4. stagnation (§14.4)
        stagnation = self._stagnation_action(position, max_r)
        if stagnation is not None:
            return [stagnation]

        actions: list[PositionAction] = []

        # 5. partial take-profit (§14.2)
        if not position.partial_tp_done and r >= self.partial_r:
            position.partial_tp_done = True
            actions.append(
                PositionAction(
                    type=PositionActionType.PARTIAL_TP,
                    qty=self._round_qty(position.qty * self.partial_fraction),
                    reason=ExitReason.PARTIAL_TAKE_PROFIT,
                )
            )

        # 6. trailing-stop ratchet update
        if position.trailing_active:
            trail_stop = self._trail_stop(position, atr, max_r)
            new_stop = self._ratchet(position, trail_stop)
            if new_stop is not None:
                position.stop_loss_price = new_stop
                actions.append(
                    PositionAction(type=PositionActionType.TRAIL_UPDATE, new_stop=new_stop)
                )
        return actions

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

    def _scenario_action(
        self,
        position: Position,
        r: Decimal,
        snapshot_5m: IndicatorSnapshot | None,
        candle: Candle | None,
        volume_ratio: Decimal | None,
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
            # reduce 50% and open a 3-bar recovery window (impl doc §14.5)
            self._scenario_recovery[position.symbol] = 3
            return PositionAction(
                type=PositionActionType.REDUCE,
                qty=self._round_qty(position.qty * Decimal("0.5")),
                reason=ExitReason.SCENARIO_INVALID,
            )
        return None

    def _scenario_invalid(
        self,
        position: Position,
        snapshot_5m: IndicatorSnapshot | None,
        candle: Candle | None,
        volume_ratio: Decimal | None,
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
        if candle is not None and volume_ratio is not None:
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
        wrong_side = (
            candle.close < position.breakout_level
            if position.side == PositionSide.LONG
            else candle.close > position.breakout_level
        )
        if wrong_side:
            count = self._break_level_fail_closes.get(position.symbol, 0) + 1
            self._break_level_fail_closes[position.symbol] = count
            return count >= 2
        self._break_level_fail_closes[position.symbol] = 0
        return False

    def _stagnation_action(
        self, position: Position, max_r: Decimal
    ) -> PositionAction | None:
        if not self.cfg.stagnation_exit.enabled:
            return None
        bars = position.bars_since_entry
        mode = position.entry_mode
        se = self.cfg.stagnation_exit
        from packages.core.enums import EntryMode

        if mode == EntryMode.PRE_BREAKOUT_SCOUT:
            if bars >= se.pre_breakout_scout.max_bars_without_breakout and max_r < Decimal("0.5"):
                return self._exit(position, ExitReason.STAGNATION)
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
                )
        elif mode == EntryMode.RETEST_CONFIRM:
            if bars >= se.retest_confirm.max_bars_without_1r and max_r < Decimal("1.0"):
                return self._exit(position, ExitReason.STAGNATION)
            if bars >= se.retest_confirm.tighten_after_bars and max_r < Decimal("0.5"):
                # tighten stop toward entry (impl doc §14.4 retest)
                tighter = self._tighten_stop(position)
                return PositionAction(type=PositionActionType.TRAIL_UPDATE, new_stop=tighter)
        return None

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
