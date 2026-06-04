"""Tests for core Decimal-based models."""

from decimal import Decimal

from packages.core.enums import PositionSide, PositionSource, PositionStatus
from packages.core.models import (
    OrderBook,
    OrderBookLevel,
    Position,
    PositionTpSlState,
)


def test_orderbook_best_prices():
    ob = OrderBook(
        symbol="BTCUSDT",
        bids=(OrderBookLevel(price=Decimal("100"), size=Decimal("1")),),
        asks=(OrderBookLevel(price=Decimal("101"), size=Decimal("2")),),
    )
    assert ob.best_bid == Decimal("100")
    assert ob.best_ask == Decimal("101")


def test_empty_orderbook_best_prices_none():
    ob = OrderBook(symbol="BTCUSDT")
    assert ob.best_bid is None
    assert ob.best_ask is None


def test_tpsl_state_protection():
    protected = PositionTpSlState(
        symbol="BTCUSDT", take_profit=Decimal("110"), stop_loss=Decimal("90")
    )
    assert protected.is_protected
    missing_sl = PositionTpSlState(
        symbol="BTCUSDT", take_profit=Decimal("110"), stop_loss=None
    )
    assert not missing_sl.is_protected


def test_decimal_precision_preserved():
    """Decimal math must not introduce float error."""
    pos = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        qty=Decimal("0.001"),
        avg_entry_price=Decimal("0.1"),
    )
    pos.qty += Decimal("0.002")
    assert pos.qty == Decimal("0.003")
    # 0.1 + 0.2 in Decimal is exactly 0.3 (float would be 0.30000000000000004)
    assert pos.avg_entry_price + Decimal("0.2") == Decimal("0.3")


def test_position_defaults():
    pos = Position(
        symbol="ETHUSDT",
        side=PositionSide.SHORT,
        qty=Decimal("1"),
        avg_entry_price=Decimal("2000"),
    )
    assert pos.status == PositionStatus.PENDING
    assert pos.source == PositionSource.BOT
    assert pos.is_bot_managed
    assert not pos.is_long
    assert pos.manual_added_qty == Decimal("0")
