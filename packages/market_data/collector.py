"""MarketDataCollector: pulls market data into CandleStore + freshness tracking.

This build uses REST polling through the ExchangeGateway (which is sufficient for
PAPER and the e2e harness, and works with FakeGateway). It records the wall-clock
timestamp of each successful refresh so the Data Quality Guard (impl doc §15) can
detect stale data. A live WebSocket feed can be layered on later behind the same
CandleStore / freshness interface.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from packages.core.models import MarketTicker, OrderBook
from packages.exchange import ExchangeGateway
from packages.market_data.candle_store import CandleStore

logger = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


class MarketDataCollector:
    def __init__(
        self,
        gateway: ExchangeGateway,
        candle_store: CandleStore,
        *,
        clock_ms: Callable[[], int] = _now_ms,
    ) -> None:
        self._gw = gateway
        self._store = candle_store
        self._clock_ms = clock_ms
        self._tickers: dict[str, MarketTicker] = {}
        self._orderbooks: dict[str, OrderBook] = {}
        self._last_kline_ms: dict[tuple[str, str], int] = {}
        self._last_ticker_ms: int | None = None
        self._last_orderbook_ms: dict[str, int] = {}

    # ---- refreshers ---------------------------------------------------- #
    async def refresh_klines(self, symbol: str, interval: str, limit: int = 200) -> None:
        candles = await self._gw.get_kline(symbol, interval, limit)
        self._store.seed(symbol, interval, candles)
        self._last_kline_ms[(symbol, interval)] = self._clock_ms()

    async def refresh_tickers(self) -> list[MarketTicker]:
        tickers = await self._gw.get_tickers()
        self._tickers = {t.symbol: t for t in tickers}
        self._last_ticker_ms = self._clock_ms()
        return tickers

    def ingest_ticker(self, ticker: MarketTicker) -> None:
        """Push a ticker from a WebSocket callback (updates freshness)."""
        self._tickers[ticker.symbol] = ticker
        self._last_ticker_ms = self._clock_ms()

    async def refresh_orderbook(self, symbol: str, depth: int = 50) -> OrderBook:
        ob = await self._gw.get_orderbook(symbol, depth)
        self._orderbooks[symbol] = ob
        self._last_orderbook_ms[symbol] = self._clock_ms()
        return ob

    # ---- accessors ----------------------------------------------------- #
    @property
    def store(self) -> CandleStore:
        return self._store

    def ticker(self, symbol: str) -> MarketTicker | None:
        return self._tickers.get(symbol)

    def tickers(self) -> list[MarketTicker]:
        return list(self._tickers.values())

    def orderbook(self, symbol: str) -> OrderBook | None:
        return self._orderbooks.get(symbol)

    def last_kline_ms(self, symbol: str, interval: str) -> int | None:
        return self._last_kline_ms.get((symbol, interval))

    def last_ticker_ms(self) -> int | None:
        return self._last_ticker_ms

    def last_orderbook_ms(self, symbol: str) -> int | None:
        return self._last_orderbook_ms.get(symbol)

    def missing_candles(self, symbol: str, interval: str) -> int:
        return self._store.missing_candles(symbol, interval)
