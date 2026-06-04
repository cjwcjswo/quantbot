"""Retest pending state and Retest Confirm checks (impl doc §10.4, §11.3).

When a breakout is Exhaustion (or otherwise not a Healthy Breakout), the engine
registers a *pending retest* at the broken level. A later candle that pulls back
to the level and holds it confirms the entry. Pending state expires after
``max_wait_candles`` or after 2 consecutive closes on the wrong side of the level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from packages.core.enums import SignalDirection
from packages.core.models import Candle
from packages.entry.candle_metrics import CandleMetrics

_WICK_THRESHOLD = Decimal("0.30")  # impl doc §11.3 lower/upper_wick_ratio >= 0.30


@dataclass
class PendingRetest:
    symbol: str
    direction: SignalDirection
    level: Decimal  # breakout_level (long) / breakdown_level (short)
    bars_waited: int = 0
    consec_beyond_fail: int = 0  # consecutive closes on the wrong side of level

    @property
    def is_long(self) -> bool:
        return self.direction == SignalDirection.LONG


class RetestManager:
    def __init__(self, *, tolerance_atr: Decimal, max_wait_candles: int) -> None:
        self._tolerance_atr = tolerance_atr
        self._max_wait = max_wait_candles
        self._pending: dict[str, PendingRetest] = {}

    def register(self, symbol: str, direction: SignalDirection, level: Decimal) -> None:
        self._pending[symbol] = PendingRetest(
            symbol=symbol, direction=direction, level=level
        )

    def get(self, symbol: str) -> PendingRetest | None:
        return self._pending.get(symbol)

    def drop(self, symbol: str) -> None:
        self._pending.pop(symbol, None)

    def on_new_bar(self, symbol: str, last_candle: Candle) -> None:
        """Advance the wait counter / wrong-side streak and expire if needed."""
        p = self._pending.get(symbol)
        if p is None:
            return
        p.bars_waited += 1
        wrong_side = (
            last_candle.close < p.level if p.is_long else last_candle.close > p.level
        )
        p.consec_beyond_fail = p.consec_beyond_fail + 1 if wrong_side else 0
        if p.bars_waited > self._max_wait or p.consec_beyond_fail >= 2:
            self.drop(symbol)

    def confirm(
        self,
        pending: PendingRetest,
        last_candle: Candle,
        metrics: CandleMetrics,
        atr: Decimal,
    ) -> bool:
        tol = self._tolerance_atr * atr
        if pending.consec_beyond_fail >= 2:
            return False
        if pending.is_long:
            near = (
                abs(last_candle.low - pending.level) <= tol
                or abs(last_candle.close - pending.level) <= tol
            )
            holds = last_candle.close >= pending.level
            rejection = (
                metrics.lower_wick_ratio >= _WICK_THRESHOLD
                or last_candle.close > last_candle.open
            )
            return near and holds and rejection
        near = (
            abs(last_candle.high - pending.level) <= tol
            or abs(last_candle.close - pending.level) <= tol
        )
        holds = last_candle.close <= pending.level
        rejection = (
            metrics.upper_wick_ratio >= _WICK_THRESHOLD
            or last_candle.close < last_candle.open
        )
        return near and holds and rejection
