"""Data Quality Guard (impl doc §15).

Blocks new entries when market data is stale, has gaps, diverges, or when any
required indicator is unavailable (NaN). Returns a reason string instead of a
bool so the caller can log/publish exactly why entry was blocked.
"""

from __future__ import annotations

from decimal import Decimal

from packages.config.settings import DataQualitySection
from packages.core.models import IndicatorSnapshot


class DataQualityGuard:
    def __init__(self, config: DataQualitySection) -> None:
        self._cfg = config

    def check(
        self,
        *,
        now_ms: int,
        last_kline_ms: int | None,
        last_ticker_ms: int | None,
        last_orderbook_ms: int | None,
        missing_candles: int = 0,
        ticker_price: Decimal | None = None,
        kline_close: Decimal | None = None,
        indicators: IndicatorSnapshot | None = None,
        require_orderbook: bool = True,
    ) -> str | None:
        """Return a block reason, or None if data is good enough to trade."""
        c = self._cfg

        def delay_sec(ts: int | None) -> float | None:
            return None if ts is None else (now_ms - ts) / 1000.0

        kline_delay = delay_sec(last_kline_ms)
        if kline_delay is None or kline_delay > c.max_kline_delay_sec:
            return "KLINE_DELAY"

        ticker_delay = delay_sec(last_ticker_ms)
        if ticker_delay is None or ticker_delay > c.max_ticker_delay_sec:
            return "TICKER_DELAY"

        if require_orderbook:
            ob_delay = delay_sec(last_orderbook_ms)
            if ob_delay is None or ob_delay > c.max_orderbook_delay_sec:
                return "ORDERBOOK_DELAY"

        if missing_candles > c.max_missing_candles and c.block_if_candle_gap_detected:
            return "MISSING_CANDLES"

        if ticker_price is not None and kline_close is not None and kline_close > 0:
            divergence = abs(ticker_price - kline_close) / kline_close * Decimal("100")
            if divergence > Decimal(str(c.max_ticker_kline_price_divergence_percent)):
                return "PRICE_DIVERGENCE"

        if indicators is not None and not indicators.valid:
            return "INDICATOR_NAN"

        return None
