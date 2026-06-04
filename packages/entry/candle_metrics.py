"""Per-candle geometry and short-window helpers (impl doc §10.1).

```
candle_range = high - low
body = abs(close - open)
upper_wick = high - max(open, close)
lower_wick = min(open, close) - low
body_ratio = body / range
upper_wick_ratio = upper_wick / range
lower_wick_ratio = lower_wick / range
close_position_in_range = (close - low) / range
```
``candle_range <= 0`` => invalid (no entry).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from packages.core.models import Candle


@dataclass(frozen=True)
class CandleMetrics:
    candle_range: Decimal
    body: Decimal
    upper_wick: Decimal
    lower_wick: Decimal
    body_ratio: Decimal
    upper_wick_ratio: Decimal
    lower_wick_ratio: Decimal
    close_position_in_range: Decimal
    valid: bool


def metrics_of(candle: Candle) -> CandleMetrics:
    rng = candle.high - candle.low
    if rng <= 0:
        zero = Decimal(0)
        return CandleMetrics(rng, zero, zero, zero, zero, zero, zero, zero, False)
    body = abs(candle.close - candle.open)
    upper = candle.high - max(candle.open, candle.close)
    lower = min(candle.open, candle.close) - candle.low
    return CandleMetrics(
        candle_range=rng,
        body=body,
        upper_wick=upper,
        lower_wick=lower,
        body_ratio=body / rng,
        upper_wick_ratio=upper / rng,
        lower_wick_ratio=lower / rng,
        close_position_in_range=(candle.close - candle.low) / rng,
        valid=True,
    )


def cumulative_move(candles: list[Candle], n: int) -> Decimal | None:
    """Signed move across the last ``n`` candles: close[-1] - open[-n].

    Positive => net rise; negative => net fall (impl doc §9 "최근 3개 누적").
    """
    if len(candles) < n or n <= 0:
        return None
    return candles[-1].close - candles[-n].open


def _true_range(prev: Candle, cur: Candle) -> Decimal:
    return max(
        cur.high - cur.low,
        abs(cur.high - prev.close),
        abs(cur.low - prev.close),
    )


def avg_true_range(candles: list[Candle], window: int) -> Decimal | None:
    """Simple mean of the true range over the last ``window`` candles."""
    if len(candles) < window + 1 or window <= 0:
        return None
    pairs = list(zip(candles, candles[1:]))[-window:]
    trs = [_true_range(p, c) for p, c in pairs]
    return sum(trs) / Decimal(window)


def count_rising_lows(candles: list[Candle], window: int = 4) -> int:
    """How many times the low increased across the last ``window`` candles."""
    lows = [c.low for c in candles[-window:]]
    return sum(1 for a, b in zip(lows, lows[1:]) if b > a)


def count_falling_highs(candles: list[Candle], window: int = 4) -> int:
    highs = [c.high for c in candles[-window:]]
    return sum(1 for a, b in zip(highs, highs[1:]) if b < a)
