"""Tests for OrderManager LIVE order policies (impl doc §12, §17.1)."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from packages.core.enums import EntryMode, OrderStatus, OrderType, Side
from packages.core.errors import OrderError
from packages.core.models import ExchangeOrder
from packages.execution import OrderManager, assert_live_new_entry_allowed
from packages.storage import OrderRow, TradeLogger
from tests.fakes import FakeGateway

_BID = Decimal("99.95")
_ASK = Decimal("100.05")


def _om(config, fill_ratio="1", *, trade_logger=None):
    gw = FakeGateway()
    gw.fill_ratio = Decimal(fill_ratio)
    return OrderManager(gw, config, trade_logger=trade_logger), gw


async def _count(session_factory, model) -> int:
    async with session_factory() as s:
        result = await s.execute(select(func.count()).select_from(model))
        return result.scalar_one()


async def test_aggressive_limit_full_fill(config):
    om, gw = _om(config, fill_ratio="1")
    out = await om.place_entry(
        symbol="BTCUSDT", side=Side.BUY, qty=Decimal("10"),
        entry_mode=EntryMode.BREAKOUT_CONFIRM, best_bid=_BID, best_ask=_ASK,
    )
    assert out.status == "FILLED"
    assert out.filled_qty == Decimal("10")
    assert gw.placed_orders[0].order_type == OrderType.AGGRESSIVE_LIMIT


async def test_aggressive_limit_records_actual_entry_mode(config):
    config.orders.scout_order_type = "AGGRESSIVE_LIMIT"
    gw = FakeGateway()
    recorded = []
    om = OrderManager(gw, config, order_sink=recorded.append)
    out = await om.place_entry(
        symbol="BTCUSDT", side=Side.BUY, qty=Decimal("10"),
        entry_mode=EntryMode.PRE_BREAKOUT_SCOUT, best_bid=_BID, best_ask=_ASK,
    )
    assert out.status == "FILLED"
    assert recorded[0].entry_mode == EntryMode.PRE_BREAKOUT_SCOUT


async def test_aggressive_partial_above_keep(config):
    om, gw = _om(config, fill_ratio="0.8")
    out = await om.place_entry(
        symbol="BTCUSDT", side=Side.BUY, qty=Decimal("10"),
        entry_mode=EntryMode.BREAKOUT_CONFIRM, best_bid=_BID, best_ask=_ASK,
    )
    assert out.status == "PARTIAL"
    assert out.filled_qty == Decimal("8.0")


async def test_aggressive_partial_below_keep_flattens(config):
    config.orders.partial_fill_min_ratio_to_keep = 0.70
    om, gw = _om(config, fill_ratio="0.5")
    out = await om.place_entry(
        symbol="BTCUSDT", side=Side.BUY, qty=Decimal("10"),
        entry_mode=EntryMode.BREAKOUT_CONFIRM, best_bid=_BID, best_ask=_ASK,
    )
    assert out.status == "REJECTED"
    assert out.reason == "PARTIAL_FILL_TOO_SMALL"
    # a reduce-only exit was issued to flatten the small fill
    exit_orders = [o for o in gw.placed_orders if o.reduce_only]
    assert exit_orders and exit_orders[-1].side == Side.SELL


async def test_limit_no_fill_gives_up_no_market(config):
    config.orders.scout_order_type = "LIMIT"
    om, gw = _om(config, fill_ratio="0")
    out = await om.place_entry(
        symbol="BTCUSDT", side=Side.BUY, qty=Decimal("10"),
        entry_mode=EntryMode.PRE_BREAKOUT_SCOUT, best_bid=_BID, best_ask=_ASK,
    )
    assert out.status == "NO_FILL"
    # never converts to MARKET (impl doc §12.3) and all attempts were LIMIT
    assert all(o.order_type == OrderType.LIMIT for o in gw.placed_orders)
    # reorder attempts: 1 reorder => 2 placements
    assert len(gw.placed_orders) == 2
    assert len(gw.cancelled) == 2


async def test_limit_no_fill_updates_runtime_order_to_cancelled(config):
    config.orders.scout_order_type = "LIMIT"
    config.orders.limit_reorder_attempts = 0
    gw = FakeGateway()
    gw.fill_ratio = Decimal("0")
    recorded = []
    om = OrderManager(gw, config, order_sink=recorded.append)

    out = await om.place_entry(
        symbol="BTCUSDT", side=Side.BUY, qty=Decimal("10"),
        entry_mode=EntryMode.PRE_BREAKOUT_SCOUT, best_bid=_BID, best_ask=_ASK,
    )

    assert out.status == "NO_FILL"
    assert recorded[-1].status == OrderStatus.CANCELLED
    assert recorded[-1].client_order_id == gw.cancelled[-1][2]


async def test_limit_no_fill_persists_cancelled_order(config, session_factory):
    config.orders.scout_order_type = "LIMIT"
    config.orders.limit_reorder_attempts = 0
    om, _gw = _om(config, fill_ratio="0", trade_logger=TradeLogger(session_factory))

    out = await om.place_entry(
        symbol="BTCUSDT", side=Side.BUY, qty=Decimal("10"),
        entry_mode=EntryMode.PRE_BREAKOUT_SCOUT, best_bid=_BID, best_ask=_ASK,
    )

    assert out.status == "NO_FILL"
    assert await _count(session_factory, OrderRow) == 1
    async with session_factory() as s:
        row = (await s.execute(select(OrderRow))).scalars().one()
    assert row.status == OrderStatus.CANCELLED.value


async def test_limit_full_fill(config):
    config.orders.retest_order_type = "LIMIT"
    om, gw = _om(config, fill_ratio="1")
    out = await om.place_entry(
        symbol="BTCUSDT", side=Side.BUY, qty=Decimal("5"),
        entry_mode=EntryMode.RETEST_CONFIRM, best_bid=_BID, best_ask=_ASK,
    )
    assert out.status == "FILLED"
    assert gw.placed_orders[0].order_type == OrderType.LIMIT


async def test_order_manager_reserves_and_clears_pending_order(config):
    gw = FakeGateway()
    reserved = []
    cleared = []
    om = OrderManager(
        gw,
        config,
        pending_order_sink=lambda cid, symbol: reserved.append((cid, symbol)),
        pending_order_clear_sink=cleared.append,
    )

    out = await om.place_entry(
        symbol="BTCUSDT", side=Side.BUY, qty=Decimal("5"),
        entry_mode=EntryMode.RETEST_CONFIRM, best_bid=_BID, best_ask=_ASK,
    )

    assert out.status == "FILLED"
    assert reserved == [(out.client_order_id, "BTCUSDT")]
    assert cleared == [out.client_order_id]


async def test_reduce_only_exit(config):
    om, gw = _om(config, fill_ratio="1")
    out = await om.place_exit(symbol="BTCUSDT", side=Side.SELL, qty=Decimal("3"))
    assert out.status == "FILLED"
    assert gw.placed_orders[-1].reduce_only is True
    assert gw.placed_orders[-1].order_type == OrderType.MARKET


async def test_order_manager_logs_orders(config, session_factory):
    om, _gw = _om(config, trade_logger=TradeLogger(session_factory))
    out = await om.place_entry(
        symbol="BTCUSDT", side=Side.BUY, qty=Decimal("5"),
        entry_mode=EntryMode.RETEST_CONFIRM, best_bid=_BID, best_ask=_ASK,
    )
    assert out.status == "FILLED"
    assert await _count(session_factory, OrderRow) == 1


def test_new_entry_market_forbidden(config):
    with pytest.raises(OrderError):
        assert_live_new_entry_allowed(OrderType.MARKET, reduce_only=False, config=config.orders)
    # reduce-only MARKET is allowed
    assert_live_new_entry_allowed(OrderType.MARKET, reduce_only=True, config=config.orders)


async def test_partial_exit_limit_first(config):
    om, gw = _om(config, fill_ratio="1")
    out = await om.place_partial_exit(
        symbol="BTCUSDT", side=Side.SELL, qty=Decimal("5"),
        limit_price=Decimal("110"), best_bid=_BID, best_ask=_ASK,
    )
    assert out.status == "FILLED"
    # first attempt is a reduce-only LIMIT (impl doc §12.2)
    first = gw.placed_orders[0]
    assert first.order_type == OrderType.LIMIT
    assert first.reduce_only is True


async def test_partial_exit_falls_back_to_market(config):
    om, gw = _om(config, fill_ratio="0")  # LIMIT does not fill
    out = await om.place_partial_exit(
        symbol="BTCUSDT", side=Side.SELL, qty=Decimal("5"),
        limit_price=Decimal("110"), best_bid=_BID, best_ask=_ASK,
    )
    # falls through to a reduce-only MARKET exit
    assert any(o.order_type == OrderType.MARKET and o.reduce_only for o in gw.placed_orders)


async def test_recover_order_by_client_id(config):
    om, gw = _om(config)
    gw.open_orders.append(
        ExchangeOrder(
            symbol="BTCUSDT", order_id="o1", client_order_id="c-123",
            side=Side.BUY, order_type="Limit", price=Decimal("100"), qty=Decimal("1"),
        )
    )
    found = await om.recover_order("BTCUSDT", "c-123")
    assert found is not None and found.order_id == "o1"
    assert await om.recover_order("BTCUSDT", "missing") is None
