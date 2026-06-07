"""CandleStore: per-(symbol, timeframe) candle storage (arch doc §6.13).

Keeps a bounded history of *confirmed* candles plus the single in-progress
candle, distinguishes the two (impl doc), detects gaps (missing candles), and
supports seeding from REST on startup ("재시작 시 최근 캔들 복구").
"""

from __future__ import annotations

from collections import deque

from packages.core.models import Candle


def interval_to_ms(interval: str) -> int:
    """Bybit kline interval string ('1','5','15',...) -> milliseconds."""
    return int(interval) * 60_000


class CandleStore:
    def __init__(self, max_candles: int = 500) -> None:
        self._max = max_candles
        self._confirmed: dict[tuple[str, str], deque[Candle]] = {}
        self._current: dict[tuple[str, str], Candle] = {}
        self._gaps: dict[tuple[str, str], int] = {}

    def _key(self, symbol: str, interval: str) -> tuple[str, str]:
        return (symbol, interval)

    def seed(self, symbol: str, interval: str, candles: list[Candle]) -> None:
        """Replace history with a REST snapshot (chronological order)."""
        key = self._key(symbol, interval)
        confirmed = [c for c in candles if c.confirmed]
        self._confirmed[key] = deque(confirmed[-self._max :], maxlen=self._max)
        self._gaps[key] = 0
        current = next((c for c in reversed(candles) if not c.confirmed), None)
        if current is None:
            self._current.pop(key, None)
        else:
            self._current[key] = current

    def update(self, candle: Candle) -> None:
        """Ingest a candle (confirmed or in-progress) and track gaps."""
        key = self._key(candle.symbol, candle.interval)
        if not candle.confirmed:
            self._current[key] = candle
            return

        confirmed = self._confirmed.setdefault(key, deque(maxlen=self._max))
        if confirmed:
            last = confirmed[-1]
            if candle.open_time_ms == last.open_time_ms:
                confirmed[-1] = candle  # replace (re-confirmation)
                return
            if candle.open_time_ms < last.open_time_ms:
                return  # stale / out of order
            step = interval_to_ms(candle.interval)
            gap = (candle.open_time_ms - last.open_time_ms) // step - 1
            if gap > 0:
                self._gaps[key] = self._gaps.get(key, 0) + gap
        confirmed.append(candle)
        # If the in-progress candle just closed, clear it.
        cur = self._current.get(key)
        if cur is not None and cur.open_time_ms <= candle.open_time_ms:
            self._current.pop(key, None)

    def get(self, symbol: str, interval: str, limit: int | None = None) -> list[Candle]:
        """Confirmed candles, oldest-first."""
        confirmed = self._confirmed.get(self._key(symbol, interval), deque())
        candles = list(confirmed)
        return candles[-limit:] if limit else candles

    def get_with_current(
        self, symbol: str, interval: str, limit: int | None = None
    ) -> list[Candle]:
        """Confirmed candles plus the in-progress candle appended (if present)."""
        key = self._key(symbol, interval)
        candles = list(self._confirmed.get(key, deque()))
        cur = self._current.get(key)
        if cur is not None:
            candles.append(cur)
        return candles[-limit:] if limit else candles

    def last_closed(self, symbol: str, interval: str) -> Candle | None:
        confirmed = self._confirmed.get(self._key(symbol, interval))
        return confirmed[-1] if confirmed else None

    def current(self, symbol: str, interval: str) -> Candle | None:
        return self._current.get(self._key(symbol, interval))

    def missing_candles(self, symbol: str, interval: str) -> int:
        return self._gaps.get(self._key(symbol, interval), 0)

    def reset_gaps(self, symbol: str, interval: str) -> None:
        self._gaps[self._key(symbol, interval)] = 0
