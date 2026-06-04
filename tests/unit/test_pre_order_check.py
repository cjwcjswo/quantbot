"""Tests for the Pre-order Check guard (impl doc §16)."""

from decimal import Decimal

from packages.core.models import OrderBook, OrderBookLevel
from packages.guards import ClockSyncGuard, PreOrderCheck


def _deep_book(bid="99.995", ask="100.005", size="1000"):
    return OrderBook(
        symbol="BTCUSDT",
        bids=(OrderBookLevel(price=Decimal(bid), size=Decimal(size)),),
        asks=(OrderBookLevel(price=Decimal(ask), size=Decimal(size)),),
    )


def _synced_clock():
    c = ClockSyncGuard(block_trading_if_drift_ms_above=1000)
    c.update(server_time_ms=1_000_000, local_time_ms=1_000_000)
    return c


def test_passes(config):
    poc = PreOrderCheck(config)
    reason = poc.check(
        orderbook=_deep_book(), order_notional=Decimal("1000"),
        expected_slippage_percent=Decimal("0.01"),
        symbol_status="Trading", clock=_synced_clock(),
    )
    assert reason is None


def test_symbol_not_trading(config):
    poc = PreOrderCheck(config)
    assert poc.check(
        orderbook=_deep_book(), order_notional=Decimal("1000"),
        expected_slippage_percent=Decimal("0.01"),
        symbol_status="PreLaunch", clock=_synced_clock(),
    ) == "SYMBOL_NOT_TRADING"


def test_clock_drift_blocks(config):
    poc = PreOrderCheck(config)
    clock = ClockSyncGuard(block_trading_if_drift_ms_above=1000)
    clock.update(server_time_ms=1_000_000, local_time_ms=1_002_000)
    assert poc.check(
        orderbook=_deep_book(), order_notional=Decimal("1000"),
        expected_slippage_percent=Decimal("0.01"),
        symbol_status="Trading", clock=clock,
    ) == "CLOCK_DRIFT"


def test_wide_spread_blocks(config):
    poc = PreOrderCheck(config)
    assert poc.check(
        orderbook=_deep_book(bid="99", ask="101"), order_notional=Decimal("1000"),
        expected_slippage_percent=Decimal("0.01"),
        symbol_status="Trading", clock=_synced_clock(),
    ) == "SPREAD_TOO_WIDE"


def test_high_slippage_blocks(config):
    poc = PreOrderCheck(config)
    assert poc.check(
        orderbook=_deep_book(), order_notional=Decimal("1000"),
        expected_slippage_percent=Decimal("0.10"),
        symbol_status="Trading", clock=_synced_clock(),
    ) == "SLIPPAGE_TOO_HIGH"


def test_insufficient_depth_blocks(config):
    poc = PreOrderCheck(config)
    thin = _deep_book(size="1")  # depth ~ 200 USDT, need notional*3
    assert poc.check(
        orderbook=thin, order_notional=Decimal("1000"),
        expected_slippage_percent=Decimal("0.01"),
        symbol_status="Trading", clock=_synced_clock(),
    ) == "INSUFFICIENT_DEPTH"
