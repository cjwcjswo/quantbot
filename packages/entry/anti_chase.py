"""Anti-Chase filter (impl doc §9): blocks chasing 1m highs (long) / lows (short).

Returns a machine-readable reason string when entry must be blocked, else None.
Missing 1m indicators are treated as a block (fail-safe).
"""

from __future__ import annotations

from decimal import Decimal

from packages.config.settings import AppConfig
from packages.core.models import Candle, IndicatorSnapshot
from packages.entry.candle_metrics import CandleMetrics, cumulative_move

_WICK_THRESHOLD = Decimal("0.30")  # impl doc §9 upper/lower_wick_ratio >= 0.30


class AntiChase:
    def __init__(self, config: AppConfig) -> None:
        ac = config.entry.anti_chase
        self.enabled = ac.enabled
        self.max_rsi_long = Decimal(str(ac.max_rsi_long))
        self.min_rsi_short = Decimal(str(ac.min_rsi_short))
        self.max_dist_atr = Decimal(str(ac.max_distance_from_ema20_atr))
        self.max_recent3_atr = Decimal(str(ac.max_recent_3_candle_move_atr))
        self.max_single_atr = Decimal(str(ac.max_single_candle_move_atr))
        self.exhaustion_vr = Decimal(str(ac.exhaustion_volume_ratio))
        self.long_min_cpr = Decimal(
            str(config.candle_quality.long_min_close_position_in_range)
        )
        self.short_max_cpr = Decimal(
            str(config.candle_quality.short_max_close_position_in_range)
        )

    def block_long(
        self,
        snapshot_1m: IndicatorSnapshot,
        candles_1m: list[Candle],
        last_metrics: CandleMetrics,
    ) -> str | None:
        if not self.enabled:
            return None
        rsi, ema, atr, vr = (
            snapshot_1m.rsi14,
            snapshot_1m.ema20,
            snapshot_1m.atr14,
            snapshot_1m.volume_ratio,
        )
        if rsi is None or ema is None or atr is None or vr is None or not candles_1m:
            return "ANTI_CHASE_DATA"
        price = candles_1m[-1].close
        if rsi >= self.max_rsi_long:
            return "RSI_OVERBOUGHT"
        if price >= ema + self.max_dist_atr * atr:
            return "PRICE_FAR_ABOVE_EMA"
        cm3 = cumulative_move(candles_1m, 3)
        if cm3 is not None and cm3 >= self.max_recent3_atr * atr:
            return "RECENT_3_RUNUP"
        single = candles_1m[-1].close - candles_1m[-1].open
        if single >= self.max_single_atr * atr:
            return "SINGLE_CANDLE_SPIKE"
        if vr >= self.exhaustion_vr and last_metrics.upper_wick_ratio >= _WICK_THRESHOLD:
            return "EXHAUSTION_UPPER_WICK"
        if last_metrics.close_position_in_range < self.long_min_cpr:
            return "WEAK_CLOSE_IN_RANGE"
        return None

    def block_short(
        self,
        snapshot_1m: IndicatorSnapshot,
        candles_1m: list[Candle],
        last_metrics: CandleMetrics,
    ) -> str | None:
        if not self.enabled:
            return None
        rsi, ema, atr, vr = (
            snapshot_1m.rsi14,
            snapshot_1m.ema20,
            snapshot_1m.atr14,
            snapshot_1m.volume_ratio,
        )
        if rsi is None or ema is None or atr is None or vr is None or not candles_1m:
            return "ANTI_CHASE_DATA"
        price = candles_1m[-1].close
        if rsi <= self.min_rsi_short:
            return "RSI_OVERSOLD"
        if price <= ema - self.max_dist_atr * atr:
            return "PRICE_FAR_BELOW_EMA"
        cm3 = cumulative_move(candles_1m, 3)
        if cm3 is not None and cm3 <= -self.max_recent3_atr * atr:
            return "RECENT_3_DROP"
        single = candles_1m[-1].open - candles_1m[-1].close
        if single >= self.max_single_atr * atr:
            return "SINGLE_CANDLE_DROP"
        if vr >= self.exhaustion_vr and last_metrics.lower_wick_ratio >= _WICK_THRESHOLD:
            return "EXHAUSTION_LOWER_WICK"
        if last_metrics.close_position_in_range > self.short_max_cpr:
            return "WEAK_CLOSE_IN_RANGE"
        return None
