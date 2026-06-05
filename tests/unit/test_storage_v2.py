"""Regression: extended TradeLogger populates the new dashboard columns."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from packages.core.enums import (
    OrderType,
    PositionSide,
    PositionSource,
    Side,
    SignalDirection,
)
from packages.core.models import Fill, Order, Position, Signal
from packages.storage import TradeLogger
from packages.storage.models import FillRow, OrderRow, PositionRow, SignalRow, TradeRow


async def _one(sf, model):
    async with sf() as s:
        return (await s.execute(select(model))).scalars().first()


async def test_log_order_populates_mode_source(session_factory):
    tl = TradeLogger(session_factory)
    order = Order(symbol="BTCUSDT", side=Side.BUY, order_type=OrderType.LIMIT,
                  qty=Decimal("0.01"), filled_qty=Decimal("0.01"),
                  avg_fill_price=Decimal("65000"))
    await tl.log_order(order, mode="PAPER", source="BOT")
    row = await _one(session_factory, OrderRow)
    assert row.mode == "PAPER"
    assert row.source == "BOT"
    assert row.filled_qty == "0.01"


async def test_log_fill_populates_mode_slippage(session_factory):
    tl = TradeLogger(session_factory)
    fill = Fill(symbol="BTCUSDT", order_id="o1", side=Side.BUY,
                price=Decimal("65000"), qty=Decimal("0.01"), fee=Decimal("0.5"))
    await tl.log_fill(fill, realized_pnl="0", mode="PAPER", slippage="0.01")
    row = await _one(session_factory, FillRow)
    assert row.mode == "PAPER"
    assert row.slippage == "0.01"


async def test_log_position_populates_fields(session_factory):
    tl = TradeLogger(session_factory)
    pos = Position(symbol="BTCUSDT", side=PositionSide.LONG, qty=Decimal("0.01"),
                   avg_entry_price=Decimal("65000"), leverage=Decimal("3"),
                   source=PositionSource.BOT)
    await tl.log_position(pos, mode="PAPER", strategy_id="trend_following",
                          protection_status="TPSL_OK", mark_price="65300")
    row = await _one(session_factory, PositionRow)
    assert row.mode == "PAPER"
    assert row.leverage == "3"
    assert row.strategy_id == "trend_following"
    assert row.protection_status == "TPSL_OK"
    assert row.mark_price == "65300"


async def test_log_position_does_not_store_reason_as_strategy_id(session_factory):
    tl = TradeLogger(session_factory)
    pos = Position(
        symbol="ETHUSDT",
        side=PositionSide.SHORT,
        qty=Decimal("0.08"),
        avg_entry_price=Decimal("1752.1"),
        leverage=Decimal("3"),
        source=PositionSource.BOT,
        strategy_reason=(
            "trend short gap=0.29% slope=-0.2694284172144818985341882628 "
            "rsi5=41.43557602046379779983748088"
        ),
    )

    await tl.log_position(pos, mode="LIVE")

    row = await _one(session_factory, PositionRow)
    assert row.strategy_id is None


async def test_log_position_uses_position_strategy_id(session_factory):
    tl = TradeLogger(session_factory)
    pos = Position(
        symbol="ETHUSDT",
        side=PositionSide.SHORT,
        qty=Decimal("0.08"),
        avg_entry_price=Decimal("1752.1"),
        strategy_id="trend_following",
        strategy_reason="trend short gap=0.29%",
    )

    await tl.log_position(pos, mode="LIVE")

    row = await _one(session_factory, PositionRow)
    assert row.strategy_id == "trend_following"


async def test_log_signal_entry_mode(session_factory):
    tl = TradeLogger(session_factory)
    sig = Signal(symbol="BTCUSDT", direction=SignalDirection.LONG,
                 strategy="trend_following", score=Decimal("8"))
    await tl.log_signal(sig, entry_mode="RETEST_CONFIRM")
    row = await _one(session_factory, SignalRow)
    assert row.entry_mode == "RETEST_CONFIRM"


async def test_log_trade_full_fields(session_factory):
    tl = TradeLogger(session_factory)
    await tl.log_trade(
        symbol="BTCUSDT", side="LONG", qty="0.01", entry_price="65000",
        exit_price="67000", realized_pnl="20", exit_reason="TAKE_PROFIT",
        strategy_id="trend_following", entry_mode="RETEST_CONFIRM", mode="PAPER",
        leverage="3", fees="1", net_pnl="19", r_multiple="2.0")
    row = await _one(session_factory, TradeRow)
    assert row.trade_id is not None
    assert row.strategy_id == "trend_following"
    assert row.entry_mode == "RETEST_CONFIRM"
    assert row.mode == "PAPER"
    assert row.r_multiple == "2.0"
    assert row.net_pnl == "19"
