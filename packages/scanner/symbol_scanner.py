"""SymbolScanner: filters the universe down to watch candidates (impl doc §7 scanner).

Applies turnover, spread, ATR%, (optional) orderbook-depth and trading-status
filters, then returns up to ``max_candidates`` symbols ordered by 24h turnover.
It does NOT decide long/short, size, or place orders (arch doc §6.11).
"""

from __future__ import annotations

import logging
from decimal import Decimal

from packages.config.settings import ScannerSection
from packages.core.models import MarketTicker, OrderBook
from packages.universe import UniverseManager

logger = logging.getLogger(__name__)


def depth_usdt_within(ob: OrderBook, pct: Decimal) -> Decimal:
    """Sum of resting USDT notional within ``pct`` percent of mid price."""
    best_bid = ob.best_bid
    best_ask = ob.best_ask
    if best_bid is None or best_ask is None:
        return Decimal(0)
    mid = (best_bid + best_ask) / Decimal(2)
    band = mid * pct / Decimal(100)
    lo, hi = mid - band, mid + band
    total = Decimal(0)
    for level in ob.bids:
        if level.price >= lo:
            total += level.price * level.size
    for level in ob.asks:
        if level.price <= hi:
            total += level.price * level.size
    return total


class SymbolScanner:
    def __init__(
        self,
        universe: UniverseManager,
        config: ScannerSection,
        *,
        min_turnover_usdt: Decimal,
    ) -> None:
        self._universe = universe
        self._cfg = config
        self._min_turnover = min_turnover_usdt

    def scan(
        self,
        tickers: list[MarketTicker],
        atr_percent_by_symbol: dict[str, Decimal],
        *,
        orderbooks: dict[str, OrderBook] | None = None,
    ) -> list[str]:
        candidates: list[tuple[str, Decimal]] = []
        for ticker in tickers:
            symbol = ticker.symbol
            if not self._universe.is_tradable(symbol):
                continue
            if not self._passes(ticker, atr_percent_by_symbol.get(symbol), orderbooks):
                continue
            candidates.append((symbol, ticker.turnover_24h))

        candidates.sort(key=lambda t: t[1], reverse=True)
        return [s for s, _ in candidates[: self._cfg.max_candidates]]

    def _passes(
        self,
        ticker: MarketTicker,
        atr_percent: Decimal | None,
        orderbooks: dict[str, OrderBook] | None,
    ) -> bool:
        c = self._cfg

        if ticker.turnover_24h < self._min_turnover:
            return False

        spread = self._spread_percent(ticker)
        if spread is None or spread > Decimal(str(c.max_spread_percent)):
            return False

        if atr_percent is None:
            return False
        if atr_percent < Decimal(str(c.min_atr_percent)):
            return False
        if atr_percent > Decimal(str(c.max_atr_percent)):
            return False

        if orderbooks is not None:
            ob = orderbooks.get(ticker.symbol)
            if ob is None:
                return False
            if depth_usdt_within(ob, Decimal("0.1")) < Decimal(
                str(c.min_orderbook_depth_usdt_0_1_percent)
            ):
                return False
            if depth_usdt_within(ob, Decimal("0.3")) < Decimal(
                str(c.min_orderbook_depth_usdt_0_3_percent)
            ):
                return False

        return True

    @staticmethod
    def _spread_percent(ticker: MarketTicker) -> Decimal | None:
        if ticker.bid_price <= 0 or ticker.ask_price <= 0:
            return None
        mid = (ticker.bid_price + ticker.ask_price) / Decimal(2)
        if mid <= 0:
            return None
        return (ticker.ask_price - ticker.bid_price) / mid * Decimal(100)
