"""Indicator math and snapshot builder (impl doc §8, arch doc §6.14).

All functions are pure and Decimal-based. They return ``None`` when there is not
enough data, which propagates to ``IndicatorSnapshot.valid = False`` so the Data
Quality Guard blocks entry (impl doc §15: any NaN indicator => no entry).

EMA uses an SMA seed; RSI and ATR use Wilder's smoothing.
"""

from __future__ import annotations

from decimal import Decimal

from packages.core.models import Candle, IndicatorSnapshot


def ema_series(values: list[Decimal], period: int) -> list[Decimal] | None:
    """Exponential moving average series (len == len(values) - period + 1)."""
    if period <= 0 or len(values) < period:
        return None
    k = Decimal(2) / Decimal(period + 1)
    seed = sum(values[:period]) / Decimal(period)
    out = [seed]
    for v in values[period:]:
        out.append((v - out[-1]) * k + out[-1])
    return out


def rsi(closes: list[Decimal], period: int = 14) -> Decimal | None:
    """Wilder's RSI."""
    if len(closes) < period + 1:
        return None
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for prev, cur in zip(closes, closes[1:]):
        delta = cur - prev
        gains.append(delta if delta > 0 else Decimal(0))
        losses.append(-delta if delta < 0 else Decimal(0))
    avg_gain = sum(gains[:period]) / Decimal(period)
    avg_loss = sum(losses[:period]) / Decimal(period)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / Decimal(period)
        avg_loss = (avg_loss * (period - 1) + losses[i]) / Decimal(period)
    if avg_loss == 0:
        return Decimal(100) if avg_gain > 0 else Decimal(50)
    rs = avg_gain / avg_loss
    return Decimal(100) - Decimal(100) / (Decimal(1) + rs)


def _true_ranges(candles: list[Candle]) -> list[Decimal]:
    trs: list[Decimal] = []
    for prev, cur in zip(candles, candles[1:]):
        trs.append(
            max(
                cur.high - cur.low,
                abs(cur.high - prev.close),
                abs(cur.low - prev.close),
            )
        )
    return trs


def atr(candles: list[Candle], period: int = 14) -> Decimal | None:
    """Wilder's Average True Range."""
    if len(candles) < period + 1:
        return None
    trs = _true_ranges(candles)
    val = sum(trs[:period]) / Decimal(period)
    for i in range(period, len(trs)):
        val = (val * (period - 1) + trs[i]) / Decimal(period)
    return val


def volume_ratio(candles: list[Candle], lookback: int = 20) -> Decimal | None:
    """Last candle volume / mean volume of the preceding ``lookback`` candles."""
    if len(candles) < lookback + 1:
        return None
    window = candles[-(lookback + 1) : -1]
    avg = sum(c.volume for c in window) / Decimal(lookback)
    if avg == 0:
        return None
    return candles[-1].volume / avg


def swing_high(candles: list[Candle], lookback: int = 20) -> Decimal | None:
    if not candles:
        return None
    window = candles[-lookback:]
    return max(c.high for c in window)


def swing_low(candles: list[Candle], lookback: int = 20) -> Decimal | None:
    if not candles:
        return None
    window = candles[-lookback:]
    return min(c.low for c in window)


class IndicatorEngine:
    """Builds an :class:`IndicatorSnapshot` from a candle series for one timeframe."""

    def __init__(
        self,
        *,
        ema_fast: int = 20,
        ema_slow: int = 50,
        rsi_period: int = 14,
        atr_period: int = 14,
        volume_lookback: int = 20,
        swing_lookback: int = 20,
        slope_candles: int = 3,
    ) -> None:
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.volume_lookback = volume_lookback
        self.swing_lookback = swing_lookback
        self.slope_candles = slope_candles

    def snapshot(
        self, symbol: str, timeframe: str, candles: list[Candle]
    ) -> IndicatorSnapshot:
        closes = [c.close for c in candles]
        close = closes[-1] if closes else Decimal(0)

        ema_fast_series = ema_series(closes, self.ema_fast)
        ema_slow_series = ema_series(closes, self.ema_slow)
        atr_val = atr(candles, self.atr_period)
        rsi_val = rsi(closes, self.rsi_period)
        vr = volume_ratio(candles, self.volume_lookback)
        sh = swing_high(candles, self.swing_lookback)
        sl = swing_low(candles, self.swing_lookback)

        ema20 = ema_fast_series[-1] if ema_fast_series else None
        ema50 = ema_slow_series[-1] if ema_slow_series else None

        # EMA20 slope over the last N candles, expressed in ATR units (impl doc §8).
        slope_atr: Decimal | None = None
        if (
            ema_fast_series is not None
            and len(ema_fast_series) > self.slope_candles
            and atr_val is not None
            and atr_val > 0
        ):
            slope_atr = (
                ema_fast_series[-1] - ema_fast_series[-1 - self.slope_candles]
            ) / atr_val

        atr_percent = (
            atr_val / close * Decimal(100)
            if atr_val is not None and close > 0
            else None
        )

        valid = (
            ema20 is not None
            and ema50 is not None
            and rsi_val is not None
            and atr_val is not None
            and atr_val > 0
            and vr is not None
        )

        return IndicatorSnapshot(
            symbol=symbol,
            timeframe=timeframe,
            close=close,
            ema20=ema20,
            ema50=ema50,
            ema20_slope_atr=slope_atr,
            rsi14=rsi_val,
            atr14=atr_val,
            atr_percent=atr_percent,
            volume_ratio=vr,
            swing_high=sh,
            swing_low=sl,
            valid=valid,
            ts_ms=candles[-1].open_time_ms if candles else 0,
        )
