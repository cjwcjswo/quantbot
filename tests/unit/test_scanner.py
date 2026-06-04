"""Tests for SymbolScanner (impl doc §7 scanner)."""

from decimal import Decimal

from packages.core.models import OrderBook, OrderBookLevel
from packages.scanner import SymbolScanner, depth_usdt_within
from packages.universe import UniverseManager
from tests.fakes import FakeGateway
from tests.fakes.builders import symbol_meta, ticker


async def _universe(config, symbols):
    gw = FakeGateway()
    gw.set_instruments([symbol_meta(symbol=s) for s in symbols])
    um = UniverseManager(gw, config.universe, now_ms=10**15)
    await um.refresh()
    return um


def _scanner(config, um):
    return SymbolScanner(
        um, config.scanner, min_turnover_usdt=Decimal(str(config.universe.min_24h_turnover_usdt))
    )


async def test_filters_low_turnover(config):
    um = await _universe(config, ["BTCUSDT", "LOWUSDT"])
    sc = _scanner(config, um)
    tickers = [
        ticker(symbol="BTCUSDT", turnover_24h="100000000"),
        ticker(symbol="LOWUSDT", turnover_24h="1000"),  # below 50M
    ]
    atr = {"BTCUSDT": Decimal("1.0"), "LOWUSDT": Decimal("1.0")}
    assert sc.scan(tickers, atr) == ["BTCUSDT"]


async def test_filters_wide_spread(config):
    um = await _universe(config, ["BTCUSDT"])
    sc = _scanner(config, um)
    # spread 1% >> max 0.08%
    tickers = [ticker(symbol="BTCUSDT", bid="99", ask="100", turnover_24h="1e8")]
    assert sc.scan(tickers, {"BTCUSDT": Decimal("1.0")}) == []


async def test_filters_atr_out_of_band(config):
    um = await _universe(config, ["A_USDT", "B_USDT"])
    sc = _scanner(config, um)
    tickers = [
        ticker(symbol="A_USDT", turnover_24h="1e8"),
        ticker(symbol="B_USDT", turnover_24h="1e8"),
    ]
    atr = {"A_USDT": Decimal("0.1"), "B_USDT": Decimal("10")}  # both out of [0.5, 5.0]
    assert sc.scan(tickers, atr) == []


async def test_sorted_by_turnover_and_capped(config):
    config.scanner.max_candidates = 2
    um = await _universe(config, ["A", "B", "C"])
    sc = _scanner(config, um)
    tickers = [
        ticker(symbol="A", turnover_24h="1e8"),
        ticker(symbol="B", turnover_24h="3e8"),
        ticker(symbol="C", turnover_24h="2e8"),
    ]
    atr = {s: Decimal("1.0") for s in ("A", "B", "C")}
    assert sc.scan(tickers, atr) == ["B", "C"]


async def test_depth_filter(config):
    um = await _universe(config, ["BTCUSDT"])
    sc = _scanner(config, um)
    tickers = [ticker(symbol="BTCUSDT", turnover_24h="1e8")]
    atr = {"BTCUSDT": Decimal("1.0")}
    thin = OrderBook(
        symbol="BTCUSDT",
        bids=(OrderBookLevel(price=Decimal("100"), size=Decimal("1")),),
        asks=(OrderBookLevel(price=Decimal("100"), size=Decimal("1")),),
    )
    assert sc.scan(tickers, atr, orderbooks={"BTCUSDT": thin}) == []


def test_depth_usdt_within():
    ob = OrderBook(
        symbol="BTCUSDT",
        bids=(
            OrderBookLevel(price=Decimal("100"), size=Decimal("10")),
            OrderBookLevel(price=Decimal("90"), size=Decimal("10")),  # outside 0.3%
        ),
        asks=(OrderBookLevel(price=Decimal("100"), size=Decimal("10")),),
    )
    # within 0.3% of mid (~100): only the 100-priced levels count = 100*10 + 100*10
    assert depth_usdt_within(ob, Decimal("0.3")) == Decimal("2000")
