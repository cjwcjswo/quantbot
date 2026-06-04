"""Trend Following Strategy (impl doc §8).

Emits a LONG or SHORT candidate when the 15m trend and 5m alignment conditions
all hold. RSI bounds (50/68 long, 32/50 short) and the ATR% band are fixed by the
doc; gap/slope/distance thresholds come from ``trend_quality`` and the setup
volume floor from ``volume``.
"""

from __future__ import annotations

from decimal import Decimal

from packages.config.settings import AppConfig
from packages.core.enums import SignalDirection
from packages.core.models import IndicatorSnapshot, Signal
from packages.strategy.base import Strategy, StrategyContext

# Fixed RSI bands from impl doc §8.
_LONG_RSI_MIN, _LONG_RSI_MAX = Decimal("50"), Decimal("68")
_SHORT_RSI_MIN, _SHORT_RSI_MAX = Decimal("32"), Decimal("50")


class TrendFollowingStrategy(Strategy):
    name = "trend_following"

    def __init__(self, config: AppConfig) -> None:
        self.cfg = config
        tq = config.trend_quality
        self.min_gap = Decimal(str(tq.min_ema_gap_percent_15m))
        self.min_slope = Decimal(str(tq.min_ema20_slope_atr_15m))
        self.min_close_dist = Decimal(str(tq.min_close_distance_from_ema20_atr_15m))
        self.min_setup_vol = Decimal(str(config.volume.min_setup_volume_ratio))
        self.atr_min = Decimal(str(config.scanner.min_atr_percent))
        self.atr_max = Decimal(str(config.scanner.max_atr_percent))

    def required_timeframes(self) -> list[str]:
        return ["5", "15"]

    def evaluate(self, ctx: StrategyContext) -> Signal | None:
        s15 = ctx.get("15")
        s5 = ctx.get("5")
        if s15 is None or s5 is None or not s15.valid or not s5.valid:
            return None
        if self._long_ok(s15, s5):
            return self._signal(ctx.symbol, SignalDirection.LONG, s15, s5)
        if self._short_ok(s15, s5):
            return self._signal(ctx.symbol, SignalDirection.SHORT, s15, s5)
        return None

    # ------------------------------------------------------------------ #
    def _atr_pct_ok(self, s5: IndicatorSnapshot) -> bool:
        ap = s5.atr_percent
        return ap is not None and self.atr_min <= ap <= self.atr_max

    def _long_ok(self, s15: IndicatorSnapshot, s5: IndicatorSnapshot) -> bool:
        if s15.ema20 <= s15.ema50:
            return False
        gap = (s15.ema20 - s15.ema50) / s15.close * Decimal(100)
        if gap < self.min_gap:
            return False
        if s15.ema20_slope_atr is None or s15.ema20_slope_atr < self.min_slope:
            return False
        if s15.atr14 is None or s15.close < s15.ema20 + self.min_close_dist * s15.atr14:
            return False
        if s5.close <= s5.ema20:
            return False
        if s5.rsi14 is None or not (_LONG_RSI_MIN <= s5.rsi14 <= _LONG_RSI_MAX):
            return False
        if s5.volume_ratio is None or s5.volume_ratio < self.min_setup_vol:
            return False
        return self._atr_pct_ok(s5)

    def _short_ok(self, s15: IndicatorSnapshot, s5: IndicatorSnapshot) -> bool:
        if s15.ema20 >= s15.ema50:
            return False
        gap = (s15.ema50 - s15.ema20) / s15.close * Decimal(100)
        if gap < self.min_gap:
            return False
        if s15.ema20_slope_atr is None or s15.ema20_slope_atr > -self.min_slope:
            return False
        if s15.atr14 is None or s15.close > s15.ema20 - self.min_close_dist * s15.atr14:
            return False
        if s5.close >= s5.ema20:
            return False
        if s5.rsi14 is None or not (_SHORT_RSI_MIN <= s5.rsi14 <= _SHORT_RSI_MAX):
            return False
        if s5.volume_ratio is None or s5.volume_ratio < self.min_setup_vol:
            return False
        return self._atr_pct_ok(s5)

    def _signal(
        self,
        symbol: str,
        direction: SignalDirection,
        s15: IndicatorSnapshot,
        s5: IndicatorSnapshot,
    ) -> Signal:
        gap = (
            (s15.ema20 - s15.ema50) if direction == SignalDirection.LONG
            else (s15.ema50 - s15.ema20)
        ) / s15.close * Decimal(100)
        score = self._score(gap, s15, s5)
        reason = (
            f"trend {direction.value.lower()} gap={gap:.2f}% "
            f"slope={s15.ema20_slope_atr} rsi5={s5.rsi14}"
        )
        return Signal(
            symbol=symbol,
            direction=direction,
            strategy=self.name,
            score=score,
            reason=reason,
        )

    def _score(
        self, gap: Decimal, s15: IndicatorSnapshot, s5: IndicatorSnapshot
    ) -> Decimal:
        """Coarse 0..10 confidence for logging / downstream prioritisation."""
        score = Decimal(0)
        score += Decimal(3) if gap >= Decimal("0.30") else Decimal(2)
        slope_mag = abs(s15.ema20_slope_atr) if s15.ema20_slope_atr is not None else Decimal(0)
        score += Decimal(3) if slope_mag >= Decimal("0.10") else Decimal(2)
        if s5.volume_ratio is not None:
            score += Decimal(2) if s5.volume_ratio >= Decimal("1.2") else Decimal(1)
        if s5.atr_percent is not None and s5.atr_percent <= Decimal("3.0"):
            score += Decimal(2)
        return min(score, Decimal(10))
