"""EntryTimingEngine: decides whether/how to enter (impl doc §10, §11).

Given a trend candidate direction plus 1m/5m/15m context, it picks one of:
  * BREAKOUT_CONFIRM  — a Healthy Breakout beyond the box (impl doc §10.2/10.3)
  * RETEST_CONFIRM    — pullback to a previously broken level holds (impl doc §11.3)
  * PRE_BREAKOUT_SCOUT — coiling just under the box, score >= min_score (impl doc §11.1)

It NEVER places orders (arch doc §6.18). Exhaustion / unhealthy breakouts create a
retest pending instead of entering (impl doc §10.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from packages.config.settings import AppConfig
from packages.core.enums import EntryMode, SignalDirection
from packages.core.models import Candle, IndicatorSnapshot
from packages.entry.anti_chase import AntiChase
from packages.entry.candle_metrics import (
    CandleMetrics,
    avg_true_range,
    count_falling_highs,
    count_rising_lows,
    metrics_of,
)
from packages.entry.retest import RetestManager


@dataclass
class EntryContext:
    symbol: str
    direction: SignalDirection  # LONG or SHORT (trend candidate)
    snapshot_1m: IndicatorSnapshot
    snapshot_5m: IndicatorSnapshot
    snapshot_15m: IndicatorSnapshot
    candles_1m: list[Candle]
    box_high: Decimal
    box_low: Decimal
    signal_score: Decimal = Decimal(0)
    signal_reason: str = ""


@dataclass(frozen=True)
class EntryDecision:
    symbol: str
    direction: SignalDirection
    entry_mode: EntryMode
    position_fraction: Decimal
    stop_atr: Decimal
    score: Decimal
    reason: str


class EntryTimingEngine:
    def __init__(self, config: AppConfig) -> None:
        self.cfg = config
        self.anti_chase = AntiChase(config)
        self.retests = RetestManager(
            tolerance_atr=Decimal(str(config.entry.retest_confirm.retest_tolerance_atr)),
            max_wait_candles=config.entry.retest_confirm.max_wait_candles,
        )

    # ------------------------------------------------------------------ #
    def evaluate(self, ctx: EntryContext) -> EntryDecision | None:
        if ctx.direction not in (SignalDirection.LONG, SignalDirection.SHORT):
            return None
        if not ctx.candles_1m:
            return None
        last = ctx.candles_1m[-1]
        m = metrics_of(last)
        atr1 = ctx.snapshot_1m.atr14
        if not m.valid or atr1 is None or atr1 <= 0:
            return None

        self.retests.on_new_bar(ctx.symbol, last)
        modes = self.cfg.entry.enabled_modes
        is_long = ctx.direction == SignalDirection.LONG

        if self._broke_out(ctx, last, atr1, is_long):
            if modes.breakout_confirm and self._healthy_breakout(ctx, m, is_long):
                return self._breakout_decision(ctx)
            # Exhaustion / unhealthy => register retest pending (impl doc §10.4).
            if modes.retest_confirm:
                level = ctx.box_high if is_long else ctx.box_low
                self.retests.register(ctx.symbol, ctx.direction, level)
            return None

        # Price still inside the box: try retest, then scout.
        if modes.retest_confirm:
            pending = self.retests.get(ctx.symbol)
            if (
                pending is not None
                and pending.direction == ctx.direction
                and self.retests.confirm(pending, last, m, atr1)
            ):
                self.retests.drop(ctx.symbol)
                return self._retest_decision(ctx)

        if modes.pre_breakout_scout:
            return self._scout_decision(ctx, last, m, atr1, is_long)

        return None

    # ------------------------------------------------------------------ #
    # breakout helpers (impl doc §10)
    # ------------------------------------------------------------------ #
    def _broke_out(
        self, ctx: EntryContext, last: Candle, atr1: Decimal, is_long: bool
    ) -> bool:
        margin = Decimal(str(self.cfg.entry.breakout_confirm.close_beyond_boundary_atr))
        if is_long:
            return last.close > ctx.box_high + margin * atr1
        return last.close < ctx.box_low - margin * atr1

    def _healthy_breakout(
        self, ctx: EntryContext, m: CandleMetrics, is_long: bool
    ) -> bool:
        vol = ctx.snapshot_1m.volume_ratio
        if vol is None:
            return False
        cq = self.cfg.candle_quality
        min_vr = Decimal(str(self.cfg.volume.min_breakout_volume_ratio))
        max_vr = Decimal(str(self.cfg.volume.max_exhaustion_volume_ratio))
        if not (min_vr <= vol < max_vr):
            return False
        if m.body_ratio < Decimal(str(cq.min_body_ratio_for_breakout)):
            return False
        opp_wick = Decimal(str(cq.max_opposite_wick_ratio_for_breakout))
        if is_long:
            if m.upper_wick_ratio > opp_wick:
                return False
            if m.close_position_in_range < Decimal(str(cq.long_min_close_position_in_range)):
                return False
            return self.anti_chase.block_long(
                ctx.snapshot_1m, ctx.candles_1m, m
            ) is None
        if m.lower_wick_ratio > opp_wick:
            return False
        if m.close_position_in_range > Decimal(str(cq.short_max_close_position_in_range)):
            return False
        return self.anti_chase.block_short(ctx.snapshot_1m, ctx.candles_1m, m) is None

    # ------------------------------------------------------------------ #
    # decision builders
    # ------------------------------------------------------------------ #
    def _breakout_decision(self, ctx: EntryContext) -> EntryDecision:
        e = self.cfg.entry.breakout_confirm
        return EntryDecision(
            symbol=ctx.symbol,
            direction=ctx.direction,
            entry_mode=EntryMode.BREAKOUT_CONFIRM,
            position_fraction=Decimal(str(e.position_fraction)),
            stop_atr=Decimal(str(e.stop_atr)),
            score=ctx.signal_score,
            reason="healthy breakout",
        )

    def _retest_decision(self, ctx: EntryContext) -> EntryDecision:
        e = self.cfg.entry.retest_confirm
        return EntryDecision(
            symbol=ctx.symbol,
            direction=ctx.direction,
            entry_mode=EntryMode.RETEST_CONFIRM,
            position_fraction=Decimal(str(e.position_fraction)),
            stop_atr=Decimal(str(e.stop_atr)),
            score=ctx.signal_score,
            reason="retest confirm",
        )

    # ------------------------------------------------------------------ #
    # scout (impl doc §11.1)
    # ------------------------------------------------------------------ #
    def _scout_decision(
        self,
        ctx: EntryContext,
        last: Candle,
        m: CandleMetrics,
        atr1: Decimal,
        is_long: bool,
    ) -> EntryDecision | None:
        if not self._scout_conditions(ctx, last, atr1, is_long):
            return None
        score = self._scout_score(ctx, last, atr1, is_long)
        if score < Decimal(str(self.cfg.entry.pre_breakout.min_score)):
            return None
        e = self.cfg.entry.pre_breakout
        return EntryDecision(
            symbol=ctx.symbol,
            direction=ctx.direction,
            entry_mode=EntryMode.PRE_BREAKOUT_SCOUT,
            position_fraction=Decimal(str(e.position_fraction)),
            stop_atr=Decimal(str(e.stop_atr)),
            score=score,
            reason="pre-breakout scout",
        )

    def _scout_conditions(
        self, ctx: EntryContext, last: Candle, atr1: Decimal, is_long: bool
    ) -> bool:
        rsi = ctx.snapshot_1m.rsi14
        vol = ctx.snapshot_1m.volume_ratio
        if rsi is None or vol is None:
            return False
        atr20 = avg_true_range(ctx.candles_1m, 20)
        atr100 = avg_true_range(ctx.candles_1m, 100)
        if atr20 is None or atr100 is None or atr20 >= atr100:  # compression required
            return False
        scout = self.cfg.entry.pre_breakout
        exhaustion_vr = Decimal(str(self.cfg.volume.max_exhaustion_volume_ratio))
        if not (Decimal(str(scout.min_volume_ratio)) <= vol < exhaustion_vr):
            return False
        dist_limit = Decimal(str(scout.max_distance_to_box_atr)) * atr1
        m = metrics_of(last)
        if is_long:
            if not (ctx.box_high - last.close <= dist_limit and last.close <= ctx.box_high):
                return False
            if count_rising_lows(ctx.candles_1m) < 2:
                return False
            if not (Decimal(str(scout.long_rsi_min)) <= rsi <= Decimal(str(scout.long_rsi_max))):
                return False
            return self.anti_chase.block_long(ctx.snapshot_1m, ctx.candles_1m, m) is None
        if not (last.close - ctx.box_low <= dist_limit and last.close >= ctx.box_low):
            return False
        if count_falling_highs(ctx.candles_1m) < 2:
            return False
        if not (Decimal(str(scout.short_rsi_min)) <= rsi <= Decimal(str(scout.short_rsi_max))):
            return False
        return self.anti_chase.block_short(ctx.snapshot_1m, ctx.candles_1m, m) is None

    def _scout_score(
        self, ctx: EntryContext, last: Candle, atr1: Decimal, is_long: bool
    ) -> Decimal:
        """Transparent 0..10 confidence (the doc fixes min_score=8 but not the
        formula). Points reward trend strength, slope, RSI position, proximity to
        the box, volatility compression and volume."""
        s15 = ctx.snapshot_15m
        scout = self.cfg.entry.pre_breakout
        score = Decimal(0)

        # trend gap (15m)
        if s15.ema20 and s15.ema50 and s15.close and s15.close > 0:
            gap = (
                (s15.ema20 - s15.ema50) if is_long else (s15.ema50 - s15.ema20)
            ) / s15.close * Decimal(100)
            score += Decimal(2) if gap >= Decimal(str(scout.score_gap_high_percent_15m)) else Decimal(1)

        # slope (15m, ATR units)
        slope = s15.ema20_slope_atr
        if slope is not None:
            mag = slope if is_long else -slope
            score += Decimal(2) if mag >= Decimal(str(scout.score_slope_high_atr_15m)) else Decimal(1)

        # 1m RSI centred
        rsi = ctx.snapshot_1m.rsi14
        if rsi is not None:
            centred = (
                Decimal(str(scout.score_long_rsi_center_min)) <= rsi <= Decimal(str(scout.score_long_rsi_center_max))
                if is_long
                else Decimal(str(scout.score_short_rsi_center_min)) <= rsi <= Decimal(str(scout.score_short_rsi_center_max))
            )
            score += Decimal(1) if centred else Decimal(0)

        # proximity to box
        dist = (ctx.box_high - last.close) if is_long else (last.close - ctx.box_low)
        if dist <= Decimal(str(scout.score_near_box_atr)) * atr1:
            score += Decimal(2)
        elif dist <= Decimal(str(scout.score_mid_box_atr)) * atr1:
            score += Decimal(1)

        # volatility compression
        atr20 = avg_true_range(ctx.candles_1m, 20)
        atr100 = avg_true_range(ctx.candles_1m, 100)
        if atr20 is not None and atr100 is not None and atr100 > 0:
            ratio = atr20 / atr100
            score += Decimal(2) if ratio <= Decimal(str(scout.score_compression_ratio)) else Decimal(1)

        # volume
        vol = ctx.snapshot_1m.volume_ratio
        if vol is not None:
            score += Decimal(2) if vol >= Decimal(str(scout.score_high_volume_ratio)) else Decimal(1)

        return min(score, Decimal(10))
