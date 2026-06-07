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
    structure_stop_price: Decimal | None = None
    stop_metadata: dict[str, object] | None = None
    compression_mode: str | None = None
    has_compression: bool | None = None
    required_score: Decimal | None = None
    compression_bonus_applied: Decimal | None = None


@dataclass(frozen=True)
class ScoutCompression:
    has_compression: bool
    bonus_applied: Decimal
    mode: str
    ratio: Decimal | None = None


def resolve_retest_stop_atr(
    atr_percent: Decimal,
    default_stop_atr: Decimal,
    adaptive_config,
) -> Decimal:
    resolved, _, _ = _resolve_retest_stop_atr_with_tier(
        atr_percent, default_stop_atr, adaptive_config
    )
    return resolved


def resolve_scout_stop_atr(
    atr_percent: Decimal,
    default_stop_atr: Decimal,
    adaptive_config,
) -> Decimal:
    resolved, _, _ = _resolve_scout_stop_atr_with_tier(
        atr_percent, default_stop_atr, adaptive_config
    )
    return resolved


def _resolve_retest_stop_atr_with_tier(
    atr_percent: Decimal,
    default_stop_atr: Decimal,
    adaptive_config,
) -> tuple[Decimal, str | None, bool]:
    return _resolve_stop_atr_with_tier(
        atr_percent,
        default_stop_atr,
        getattr(adaptive_config, "enabled", False),
        getattr(adaptive_config, "retest_atr_percent_tiers", None) or [],
    )


def _resolve_scout_stop_atr_with_tier(
    atr_percent: Decimal,
    default_stop_atr: Decimal,
    adaptive_config,
) -> tuple[Decimal, str | None, bool]:
    return _resolve_stop_atr_with_tier(
        atr_percent,
        default_stop_atr,
        getattr(adaptive_config, "enabled", False),
        getattr(adaptive_config, "scout_atr_percent_tiers", None) or [],
    )


def _resolve_stop_atr_with_tier(
    atr_percent: Decimal,
    default_stop_atr: Decimal,
    enabled: bool,
    raw_tiers,
) -> tuple[Decimal, str | None, bool]:
    if not enabled:
        return default_stop_atr, None, False

    tiers: list[tuple[Decimal, Decimal]] = []
    invalid = False
    for tier in raw_tiers:
        try:
            max_atr_percent = Decimal(str(tier.max_atr_percent))
            stop_atr = Decimal(str(tier.stop_atr))
        except Exception:  # noqa: BLE001 - config model validation reports the root issue
            invalid = True
            continue
        if max_atr_percent <= 0 or stop_atr <= 0:
            invalid = True
            continue
        tiers.append((max_atr_percent, stop_atr))

    if not tiers:
        return default_stop_atr, None, True

    previous = Decimal("0")
    for max_atr_percent, stop_atr in sorted(tiers, key=lambda item: item[0]):
        if atr_percent <= max_atr_percent:
            return (
                stop_atr,
                f"{_tier_label(previous)}-{_tier_label(max_atr_percent)}",
                invalid,
            )
        previous = max_atr_percent
    return default_stop_atr, None, invalid


def _tier_label(value: Decimal) -> str:
    if value == 0:
        return "0"
    if value < 1:
        return f"{value:.2f}"
    return format(value, "f")


class EntryTimingEngine:
    def __init__(self, config: AppConfig) -> None:
        self.cfg = config
        self.anti_chase = AntiChase(config)
        self.retests = RetestManager(
            tolerance_atr=Decimal(str(config.entry.retest_confirm.retest_tolerance_atr)),
            max_wait_candles=config.entry.retest_confirm.max_wait_candles,
        )
        self.last_no_entry_reason: dict | None = None

    # ------------------------------------------------------------------ #
    def evaluate(self, ctx: EntryContext) -> EntryDecision | None:
        self.last_no_entry_reason = None
        if ctx.direction not in (SignalDirection.LONG, SignalDirection.SHORT):
            self._record_no_entry("entry_timing", "TREND_CONDITION_FAILED")
            return None
        if not ctx.candles_1m:
            self._record_no_entry("entry_timing", "NO_CANDLES")
            return None
        last = ctx.candles_1m[-1]
        m = metrics_of(last)
        atr1 = ctx.snapshot_1m.atr14
        if not m.valid or atr1 is None or atr1 <= 0:
            self._record_no_entry("entry_timing", "INVALID_CANDLE_OR_ATR")
            return None

        self.retests.on_new_bar(ctx.symbol, last)
        modes = self.cfg.entry.enabled_modes
        is_long = ctx.direction == SignalDirection.LONG

        if self._broke_out(ctx, last, atr1, is_long):
            quality_reason = self._breakout_quality_reason(ctx, m, is_long)
            if modes.breakout_confirm and quality_reason is None:
                return self._breakout_decision(ctx)
            # Exhaustion / unhealthy => register retest pending (impl doc §10.4).
            if modes.retest_confirm:
                level = ctx.box_high if is_long else ctx.box_low
                self.retests.register(ctx.symbol, ctx.direction, level)
            reason_code = (
                "BREAKOUT_EXHAUSTION"
                if quality_reason == "VOLUME_EXHAUSTION"
                else "BREAKOUT_NOT_HEALTHY"
            )
            anti_chase_reason = self._anti_chase_detail(quality_reason)
            self._record_no_entry(
                "entry_timing",
                reason_code,
                entry_mode_candidate=EntryMode.BREAKOUT_CONFIRM.value,
                anti_chase_reason=anti_chase_reason,
                breakout_quality_reason=quality_reason,
                retest_pending_status="REGISTERED" if modes.retest_confirm else "DISABLED",
            )
            return None

        # Price still inside the box: try retest, then scout.
        if modes.retest_confirm:
            pending = self.retests.get(ctx.symbol)
            if pending is not None and pending.direction == ctx.direction:
                if self.retests.confirm(pending, last, m, atr1):
                    self.retests.drop(ctx.symbol)
                    return self._retest_decision(ctx, last, atr1)
                self._record_no_entry(
                    "entry_timing",
                    "RETEST_TOO_FAR_FROM_LEVEL",
                    entry_mode_candidate=EntryMode.RETEST_CONFIRM.value,
                    retest_pending_status=f"WAITING:{pending.bars_waited}",
                )

        if modes.pre_breakout_scout:
            decision = self._scout_decision(ctx, last, m, atr1, is_long)
            if decision is not None:
                return decision

        if self.last_no_entry_reason is None:
            self._record_no_entry("entry_timing", "SCOUT_CONDITIONS_FAILED")
        return None

    def _record_no_entry(
        self,
        failed_stage: str,
        reason_code: str,
        **extra,
    ) -> None:
        anti_chase_reason = self._anti_chase_detail(reason_code)
        if anti_chase_reason is not None:
            reason_code = reason_code.split(":", 1)[0]
            extra.setdefault("anti_chase_reason", anti_chase_reason)
        self.last_no_entry_reason = {
            "failed_stage": failed_stage,
            "reason_code": reason_code,
            **{k: v for k, v in extra.items() if v is not None},
        }

    @staticmethod
    def _anti_chase_detail(reason: str | None) -> str | None:
        if reason is None or ":" not in reason:
            return None
        prefix, detail = reason.split(":", 1)
        if prefix in {"ANTI_CHASE_LONG", "ANTI_CHASE_SHORT"}:
            return detail
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

    def _breakout_quality_reason(
        self, ctx: EntryContext, m: CandleMetrics, is_long: bool
    ) -> str | None:
        vol = ctx.snapshot_1m.volume_ratio
        if vol is None:
            return "VOLUME_MISSING"
        cq = self.cfg.candle_quality
        min_vr = Decimal(str(self.cfg.entry.breakout_confirm.volume_min_ratio))
        max_vr = Decimal(str(self.cfg.volume.max_exhaustion_volume_ratio))
        if vol < min_vr:
            return "VOLUME_TOO_LOW"
        if vol >= max_vr:
            return "VOLUME_EXHAUSTION"
        if m.body_ratio < Decimal(str(cq.min_body_ratio_for_breakout)):
            return "BODY_TOO_SMALL"
        opp_wick = Decimal(str(cq.max_opposite_wick_ratio_for_breakout))
        if is_long:
            if m.upper_wick_ratio > opp_wick:
                return "OPPOSITE_WICK_TOO_LARGE"
            if m.close_position_in_range < Decimal(str(cq.long_min_close_position_in_range)):
                return "WEAK_CLOSE_IN_RANGE"
            anti = self.anti_chase.block_long(ctx.snapshot_1m, ctx.candles_1m, m)
            return f"ANTI_CHASE_LONG:{anti}" if anti else None
        if m.lower_wick_ratio > opp_wick:
            return "OPPOSITE_WICK_TOO_LARGE"
        if m.close_position_in_range > Decimal(str(cq.short_max_close_position_in_range)):
            return "WEAK_CLOSE_IN_RANGE"
        anti = self.anti_chase.block_short(ctx.snapshot_1m, ctx.candles_1m, m)
        return f"ANTI_CHASE_SHORT:{anti}" if anti else None

    def _healthy_breakout(
        self, ctx: EntryContext, m: CandleMetrics, is_long: bool
    ) -> bool:
        return self._breakout_quality_reason(ctx, m, is_long) is None

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

    def _retest_decision(
        self, ctx: EntryContext, last: Candle, atr1: Decimal
    ) -> EntryDecision:
        e = self.cfg.entry.retest_confirm
        default_stop_atr = Decimal(str(e.stop_atr or 1.3))
        atr_percent = self._atr_percent_1m(ctx, last, atr1)
        resolved_stop_atr, tier, adaptive_invalid = _resolve_retest_stop_atr_with_tier(
            atr_percent,
            default_stop_atr,
            self.cfg.volatility_adaptive_stop,
        )
        structure_enabled = self._structure_stop_enabled(EntryMode.RETEST_CONFIRM)
        swing_low: Decimal | None = None
        swing_high: Decimal | None = None
        structure_stop_price: Decimal | None = None
        structure_unavailable = False

        if structure_enabled:
            buffer_atr = Decimal(str(self.cfg.structure_stop.buffer_atr))
            if ctx.direction == SignalDirection.LONG:
                swing_low = self._retest_swing_low(ctx)
                if swing_low is not None:
                    structure_stop_price = swing_low - atr1 * buffer_atr
                else:
                    structure_unavailable = True
            else:
                swing_high = self._retest_swing_high(ctx)
                if swing_high is not None:
                    structure_stop_price = swing_high + atr1 * buffer_atr
                else:
                    structure_unavailable = True

        metadata = {
            "entry_mode": EntryMode.RETEST_CONFIRM.value,
            "symbol": ctx.symbol,
            "side": ctx.direction.value,
            "atr_percent_1m": str(atr_percent),
            "default_stop_atr": str(default_stop_atr),
            "resolved_stop_atr": str(resolved_stop_atr),
            "adaptive_stop_enabled": self.cfg.volatility_adaptive_stop.enabled,
            "adaptive_stop_tier": tier,
            "adaptive_stop_config_invalid": adaptive_invalid or None,
            "adaptive_stop_warning": "ADAPTIVE_STOP_CONFIG_INVALID"
            if adaptive_invalid
            else None,
            "structure_stop_enabled": structure_enabled,
            "structure_stop_price": str(structure_stop_price)
            if structure_stop_price is not None
            else None,
            "retest_swing_low": str(swing_low) if swing_low is not None else None,
            "retest_swing_high": str(swing_high) if swing_high is not None else None,
            "structure_stop_warning": "STRUCTURE_STOP_UNAVAILABLE"
            if structure_unavailable
            else None,
        }
        return EntryDecision(
            symbol=ctx.symbol,
            direction=ctx.direction,
            entry_mode=EntryMode.RETEST_CONFIRM,
            position_fraction=Decimal(str(e.position_fraction)),
            stop_atr=resolved_stop_atr,
            score=ctx.signal_score,
            reason="retest confirm",
            structure_stop_price=structure_stop_price,
            stop_metadata={k: v for k, v in metadata.items() if v is not None},
        )

    def _atr_percent_1m(
        self, ctx: EntryContext, last: Candle, atr1: Decimal
    ) -> Decimal:
        if ctx.snapshot_1m.atr_percent is not None:
            return ctx.snapshot_1m.atr_percent
        price = ctx.snapshot_1m.close or last.close
        if price <= 0:
            return Decimal("0")
        return atr1 / price * Decimal(100)

    def _structure_stop_enabled(self, entry_mode: EntryMode) -> bool:
        c = self.cfg.structure_stop
        if not c.enabled:
            return False
        if entry_mode == EntryMode.PRE_BREAKOUT_SCOUT and not c.use_structure_stop_for_scout:
            return False
        if entry_mode == EntryMode.RETEST_CONFIRM and not c.use_structure_stop_for_retest:
            return False
        return entry_mode.value in set(c.apply_to_entry_modes)

    def _scout_swing_low(self, ctx: EntryContext) -> Decimal | None:
        recent = ctx.candles_1m[-5:]
        if recent:
            return min(c.low for c in recent)
        return ctx.snapshot_1m.swing_low

    def _scout_swing_high(self, ctx: EntryContext) -> Decimal | None:
        recent = ctx.candles_1m[-5:]
        if recent:
            return max(c.high for c in recent)
        return ctx.snapshot_1m.swing_high

    def _retest_swing_low(self, ctx: EntryContext) -> Decimal | None:
        recent = ctx.candles_1m[-5:]
        if recent:
            return min(c.low for c in recent)
        return ctx.snapshot_1m.swing_low

    def _retest_swing_high(self, ctx: EntryContext) -> Decimal | None:
        recent = ctx.candles_1m[-5:]
        if recent:
            return max(c.high for c in recent)
        return ctx.snapshot_1m.swing_high

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
        compression = self._scout_compression(ctx)
        score = self._scout_score(ctx, last, atr1, is_long, compression)
        required_score = self._scout_required_score(compression.has_compression)
        position_fraction = self._scout_position_fraction(compression.has_compression)
        meta = self._scout_log_meta(
            compression=compression,
            score=score,
            required_score=required_score,
            position_fraction=position_fraction,
        )
        reasons = self._scout_condition_reasons(
            ctx, last, atr1, is_long, compression
        )
        if reasons:
            self._record_no_entry(
                "entry_timing",
                reasons[0],
                entry_mode_candidate=EntryMode.PRE_BREAKOUT_SCOUT.value,
                scout_failed_conditions=reasons,
                **meta,
            )
            return None
        if score < required_score:
            reason_code = (
                "SCOUT_SCORE_TOO_LOW"
                if compression.has_compression
                else "SCOUT_SCORE_TOO_LOW_NO_COMPRESSION"
            )
            self._record_no_entry(
                "entry_timing",
                reason_code,
                entry_mode_candidate=EntryMode.PRE_BREAKOUT_SCOUT.value,
                **meta,
            )
            return None
        e = self.cfg.entry.pre_breakout
        default_stop_atr = Decimal(str(e.stop_atr or 0.7))
        atr_percent = self._atr_percent_1m(ctx, last, atr1)
        resolved_stop_atr, tier, adaptive_invalid = _resolve_scout_stop_atr_with_tier(
            atr_percent,
            default_stop_atr,
            self.cfg.volatility_adaptive_stop,
        )
        structure_enabled = self._structure_stop_enabled(EntryMode.PRE_BREAKOUT_SCOUT)
        swing_low: Decimal | None = None
        swing_high: Decimal | None = None
        structure_stop_price: Decimal | None = None
        structure_unavailable = False

        if structure_enabled:
            buffer_atr = Decimal(str(self.cfg.structure_stop.buffer_atr))
            if ctx.direction == SignalDirection.LONG:
                swing_low = self._scout_swing_low(ctx)
                if swing_low is not None:
                    structure_stop_price = swing_low - atr1 * buffer_atr
                else:
                    structure_unavailable = True
            else:
                swing_high = self._scout_swing_high(ctx)
                if swing_high is not None:
                    structure_stop_price = swing_high + atr1 * buffer_atr
                else:
                    structure_unavailable = True

        stop_metadata = {
            "entry_mode": EntryMode.PRE_BREAKOUT_SCOUT.value,
            "symbol": ctx.symbol,
            "side": ctx.direction.value,
            "atr_percent_1m": str(atr_percent),
            "default_stop_atr": str(default_stop_atr),
            "resolved_stop_atr": str(resolved_stop_atr),
            "adaptive_stop_enabled": self.cfg.volatility_adaptive_stop.enabled,
            "adaptive_stop_tier": tier,
            "adaptive_stop_config_invalid": adaptive_invalid or None,
            "adaptive_stop_warning": "ADAPTIVE_STOP_CONFIG_INVALID"
            if adaptive_invalid
            else None,
            "structure_stop_enabled": structure_enabled,
            "structure_stop_price": str(structure_stop_price)
            if structure_stop_price is not None
            else None,
            "scout_swing_low": str(swing_low) if swing_low is not None else None,
            "scout_swing_high": str(swing_high) if swing_high is not None else None,
            "structure_stop_warning": "STRUCTURE_STOP_UNAVAILABLE"
            if structure_unavailable
            else None,
        }
        return EntryDecision(
            symbol=ctx.symbol,
            direction=ctx.direction,
            entry_mode=EntryMode.PRE_BREAKOUT_SCOUT,
            position_fraction=position_fraction,
            stop_atr=resolved_stop_atr,
            score=score,
            reason=f"pre-breakout scout {compression.mode.lower()}",
            structure_stop_price=structure_stop_price,
            stop_metadata={k: v for k, v in stop_metadata.items() if v is not None},
            compression_mode=compression.mode,
            has_compression=compression.has_compression,
            required_score=required_score,
            compression_bonus_applied=compression.bonus_applied,
        )

    def _scout_condition_reason(
        self,
        ctx: EntryContext,
        last: Candle,
        atr1: Decimal,
        is_long: bool,
        compression: ScoutCompression,
    ) -> str | None:
        reasons = self._scout_condition_reasons(
            ctx, last, atr1, is_long, compression
        )
        return reasons[0] if reasons else None

    def _scout_condition_reasons(
        self,
        ctx: EntryContext,
        last: Candle,
        atr1: Decimal,
        is_long: bool,
        compression: ScoutCompression,
    ) -> list[str]:
        rsi = ctx.snapshot_1m.rsi14
        vol = ctx.snapshot_1m.volume_ratio
        if rsi is None or vol is None:
            return ["SCOUT_DATA_MISSING"]
        if self.cfg.entry.pre_breakout.require_compression and not compression.has_compression:
            return ["SCOUT_NO_COMPRESSION"]
        scout = self.cfg.entry.pre_breakout
        reasons: list[str] = []
        dist_limit = Decimal(str(scout.max_distance_to_box_atr)) * atr1
        exhaustion_vr = Decimal(str(self.cfg.volume.max_exhaustion_volume_ratio))
        m = metrics_of(last)
        if is_long:
            if not (ctx.box_high - last.close <= dist_limit and last.close <= ctx.box_high):
                reasons.append("SCOUT_TOO_FAR_FROM_BOX")
        else:
            if not (last.close - ctx.box_low <= dist_limit and last.close >= ctx.box_low):
                reasons.append("SCOUT_TOO_FAR_FROM_BOX")
        if vol < Decimal(str(scout.min_volume_ratio)):
            reasons.append("VOLUME_TOO_LOW")
        elif vol >= exhaustion_vr:
            reasons.append("BREAKOUT_EXHAUSTION")
        if is_long:
            if count_rising_lows(ctx.candles_1m) < 2:
                reasons.append("SCOUT_STRUCTURE_WEAK")
            if not (Decimal(str(scout.long_rsi_min)) <= rsi <= Decimal(str(scout.long_rsi_max))):
                reasons.append("TREND_CONDITION_FAILED")
            anti = self.anti_chase.block_long(ctx.snapshot_1m, ctx.candles_1m, m)
            if anti:
                reasons.append(f"ANTI_CHASE_LONG:{anti}")
        else:
            if count_falling_highs(ctx.candles_1m) < 2:
                reasons.append("SCOUT_STRUCTURE_WEAK")
            if not (Decimal(str(scout.short_rsi_min)) <= rsi <= Decimal(str(scout.short_rsi_max))):
                reasons.append("TREND_CONDITION_FAILED")
            anti = self.anti_chase.block_short(ctx.snapshot_1m, ctx.candles_1m, m)
            if anti:
                reasons.append(f"ANTI_CHASE_SHORT:{anti}")
        return reasons

    def _scout_conditions(
        self, ctx: EntryContext, last: Candle, atr1: Decimal, is_long: bool
    ) -> bool:
        compression = self._scout_compression(ctx)
        return self._scout_condition_reason(
            ctx, last, atr1, is_long, compression
        ) is None

    def _scout_score(
        self,
        ctx: EntryContext,
        last: Candle,
        atr1: Decimal,
        is_long: bool,
        compression: ScoutCompression | None = None,
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

        compression = compression or self._scout_compression(ctx)
        score += compression.bonus_applied

        # volume
        vol = ctx.snapshot_1m.volume_ratio
        if vol is not None:
            score += Decimal(2) if vol >= Decimal(str(scout.score_high_volume_ratio)) else Decimal(1)

        return min(score, Decimal(10))

    def _scout_compression(self, ctx: EntryContext) -> ScoutCompression:
        scout = self.cfg.entry.pre_breakout
        atr20 = avg_true_range(ctx.candles_1m, 20)
        atr100 = avg_true_range(ctx.candles_1m, 100)
        ratio = atr20 / atr100 if atr20 is not None and atr100 and atr100 > 0 else None
        has_compression = (
            ratio is not None
            and ratio <= Decimal(str(scout.score_compression_ratio))
        )
        bonus = (
            Decimal(str(scout.compression_bonus_score))
            if has_compression
            else Decimal("0")
        )
        return ScoutCompression(
            has_compression=has_compression,
            bonus_applied=bonus,
            mode="WITH_COMPRESSION" if has_compression else "WITHOUT_COMPRESSION",
            ratio=ratio,
        )

    def _scout_required_score(self, has_compression: bool) -> Decimal:
        scout = self.cfg.entry.pre_breakout
        if has_compression:
            value = scout.compression_min_score
            if value is None:
                value = scout.min_score
        else:
            value = scout.no_compression_min_score
            if value is None:
                value = scout.min_score + 1
        return Decimal(str(value))

    def _scout_position_fraction(self, has_compression: bool) -> Decimal:
        scout = self.cfg.entry.pre_breakout
        if has_compression:
            value = scout.compression_position_fraction
            if value is None:
                value = scout.position_fraction
            return Decimal(str(value))
        value = scout.no_compression_position_fraction
        if value is None:
            return min(Decimal(str(scout.position_fraction)), Decimal("0.20"))
        return Decimal(str(value))

    @staticmethod
    def _scout_log_meta(
        *,
        compression: ScoutCompression,
        score: Decimal,
        required_score: Decimal,
        position_fraction: Decimal,
    ) -> dict:
        return {
            "has_compression": compression.has_compression,
            "compression_bonus_applied": str(compression.bonus_applied),
            "scout_score": str(score),
            "required_scout_score": str(required_score),
            "position_fraction": str(position_fraction),
            "compression_mode": compression.mode,
        }
