"""SymbolScanner: filters the universe down to watch candidates (impl doc §7 scanner).

Applies turnover, spread, ATR%, (optional) orderbook-depth and trading-status
filters, then returns up to ``max_candidates`` symbols ordered by scanner score.
It does NOT decide long/short, size, or place orders (arch doc §6.11).
"""

from __future__ import annotations

import logging
from decimal import Decimal

from packages.config.settings import ScannerSection
from packages.core.models import IndicatorSnapshot, MarketTicker, OrderBook
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
        snapshots_15m: dict[str, IndicatorSnapshot] | None = None,
        snapshots_5m: dict[str, IndicatorSnapshot] | None = None,
    ) -> list[str]:
        eligible: list[MarketTicker] = []
        for ticker in tickers:
            symbol = ticker.symbol
            if not self._universe.is_tradable(symbol):
                continue
            if not self._passes(ticker, atr_percent_by_symbol.get(symbol), orderbooks):
                continue
            eligible.append(ticker)

        if not eligible:
            return []

        min_turnover = min(t.turnover_24h for t in eligible)
        max_turnover = max(t.turnover_24h for t in eligible)
        scored = [
            (
                ticker.symbol,
                scanner_score(
                    ticker=ticker,
                    atr_percent=atr_percent_by_symbol[ticker.symbol],
                    min_turnover=min_turnover,
                    max_turnover=max_turnover,
                    snapshot_15m=(snapshots_15m or {}).get(ticker.symbol),
                    snapshot_5m=(snapshots_5m or {}).get(ticker.symbol),
                ),
                ticker.turnover_24h,
            )
            for ticker in eligible
        ]
        scored.sort(key=lambda t: (t[1], t[2]), reverse=True)
        return [s for s, _, _ in scored[: self._cfg.max_candidates]]

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


def scanner_score(
    *,
    ticker: MarketTicker,
    atr_percent: Decimal,
    min_turnover: Decimal,
    max_turnover: Decimal,
    snapshot_15m: IndicatorSnapshot | None = None,
    snapshot_5m: IndicatorSnapshot | None = None,
) -> Decimal:
    """Composite 0..100 watchlist score.

    The scanner still filters for tradability/liquidity first; this score only
    ranks already-eligible symbols so candidates with live trend/volume context
    are preferred over turnover alone.
    """
    turnover = _turnover_score(ticker.turnover_24h, min_turnover, max_turnover)
    atr = _atr_score(atr_percent)
    trend = _trend_potential_score(snapshot_15m)
    volume = _volume_score(snapshot_5m)
    spread = _spread_score(SymbolScanner._spread_percent(ticker))
    return (
        turnover * Decimal("0.30")
        + atr * Decimal("0.25")
        + trend * Decimal("0.25")
        + volume * Decimal("0.10")
        + spread * Decimal("0.10")
    )


def _turnover_score(value: Decimal, min_value: Decimal, max_value: Decimal) -> Decimal:
    if max_value <= 0:
        return Decimal(0)
    if max_value == min_value:
        return Decimal(100)
    return (value - min_value) / (max_value - min_value) * Decimal(100)


def _atr_score(value: Decimal) -> Decimal:
    if Decimal("0.5") <= value <= Decimal("3.5"):
        return Decimal(100)
    if Decimal("3.5") < value <= Decimal("5.0"):
        return Decimal(70)
    return Decimal(40)


def _trend_potential_score(snapshot: IndicatorSnapshot | None) -> Decimal:
    if snapshot is None or snapshot.ema20 is None or snapshot.ema50 is None:
        return Decimal(20)
    slope = snapshot.ema20_slope_atr or Decimal(0)
    if (snapshot.ema20 > snapshot.ema50 and slope > 0) or (
        snapshot.ema20 < snapshot.ema50 and slope < 0
    ):
        return Decimal(100)
    if snapshot.ema20 != snapshot.ema50 or slope != 0:
        return Decimal(60)
    return Decimal(20)


def _volume_score(snapshot: IndicatorSnapshot | None) -> Decimal:
    value = snapshot.volume_ratio if snapshot is not None else None
    if value is None:
        return Decimal(20)
    if value >= Decimal("1.0"):
        return Decimal(100)
    if value >= Decimal("0.6"):
        return Decimal(60)
    return Decimal(20)


def _spread_score(value: Decimal | None) -> Decimal:
    if value is None:
        return Decimal(20)
    if value <= Decimal("0.05"):
        return Decimal(100)
    if value <= Decimal("0.10"):
        return Decimal(70)
    return Decimal(0)
