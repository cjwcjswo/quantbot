"""Tests for ExchangeGateway protocol conformance and FakeGateway behavior."""

from decimal import Decimal

import pytest

from packages.core.enums import OrderStatus, OrderType, PositionSide, Side
from packages.core.models import (
    MarketTicker,
    OrderRequest,
    TradingStopRequest,
)
from packages.exchange import ExchangeGateway
from tests.fakes import FakeGateway


def test_fake_gateway_satisfies_protocol():
    assert isinstance(FakeGateway(), ExchangeGateway)


async def test_place_order_opens_position():
    gw = FakeGateway()
    gw.set_ticker(
        MarketTicker(
            symbol="BTCUSDT",
            last_price=Decimal("100"),
            bid_price=Decimal("99.9"),
            ask_price=Decimal("100.1"),
        )
    )
    res = await gw.place_order(
        OrderRequest(
            symbol="BTCUSDT",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            qty=Decimal("2"),
            price=Decimal("100"),
        )
    )
    assert res.status == OrderStatus.FILLED
    assert res.filled_qty == Decimal("2")
    positions = await gw.get_positions()
    assert len(positions) == 1
    assert positions[0].side == PositionSide.LONG
    assert positions[0].size == Decimal("2")
    assert positions[0].avg_price == Decimal("100")


async def test_partial_fill_ratio():
    gw = FakeGateway()
    gw.fill_ratio = Decimal("0.5")
    res = await gw.place_order(
        OrderRequest(
            symbol="ETHUSDT",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            qty=Decimal("4"),
            price=Decimal("2000"),
        )
    )
    assert res.status == OrderStatus.PARTIALLY_FILLED
    assert res.filled_qty == Decimal("2")


async def test_opposite_fill_reduces_position():
    gw = FakeGateway()
    await gw.place_order(
        OrderRequest(
            symbol="BTCUSDT", side=Side.BUY, order_type=OrderType.LIMIT,
            qty=Decimal("3"), price=Decimal("100"),
        )
    )
    await gw.place_order(
        OrderRequest(
            symbol="BTCUSDT", side=Side.SELL, order_type=OrderType.MARKET,
            qty=Decimal("1"), price=Decimal("105"), reduce_only=True,
        )
    )
    pos = (await gw.get_positions())[0]
    assert pos.size == Decimal("2")
    assert pos.side == PositionSide.LONG
    assert pos.avg_price == Decimal("100")  # reducing keeps avg


async def test_set_and_read_tpsl():
    gw = FakeGateway()
    await gw.place_order(
        OrderRequest(
            symbol="BTCUSDT", side=Side.BUY, order_type=OrderType.LIMIT,
            qty=Decimal("1"), price=Decimal("100"),
        )
    )
    await gw.set_trading_stop(
        TradingStopRequest(
            symbol="BTCUSDT",
            take_profit=Decimal("120"),
            stop_loss=Decimal("90"),
        )
    )
    state = await gw.get_position_tpsl("BTCUSDT")
    assert state.is_protected
    assert state.take_profit == Decimal("120")
    assert state.stop_loss == Decimal("90")


async def test_cancel_order_removes_open_order():
    gw = FakeGateway()
    from packages.core.models import ExchangeOrder

    gw.open_orders.append(
        ExchangeOrder(
            symbol="BTCUSDT", order_id="x1", client_order_id="c1",
            side=Side.BUY, order_type="Limit", price=Decimal("100"), qty=Decimal("1"),
        )
    )
    await gw.cancel_order("BTCUSDT", "x1", None)
    assert await gw.get_open_orders("BTCUSDT") == []
    assert gw.cancelled == [("BTCUSDT", "x1", None)]
