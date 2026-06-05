"""Tests for storage models + TradeLogger persistence (arch doc §7)."""

from decimal import Decimal

from sqlalchemy import func, select

from packages.core.enums import (
    EntryMode,
    PositionSide,
    PositionStatus,
    Side,
    SignalDirection,
)
from packages.core.events import BotEvent, BotEventType
from packages.core.models import Fill, Position, Signal
from packages.storage import (
    BotEventRow,
    CommandLogRow,
    FillRow,
    PositionRow,
    SignalRow,
    TradeRow,
    TradeLogger,
)


async def _count(session_factory, model) -> int:
    async with session_factory() as s:
        result = await s.execute(select(func.count()).select_from(model))
        return result.scalar_one()


async def test_event_sink_persists(session_factory):
    tl = TradeLogger(session_factory)
    await tl(BotEvent(type=BotEventType.POSITION_OPENED, symbol="BTCUSDT", message="x"))
    assert await _count(session_factory, BotEventRow) == 1


async def test_log_signal(session_factory):
    tl = TradeLogger(session_factory)
    await tl.log_signal(
        Signal(symbol="BTCUSDT", direction=SignalDirection.LONG,
               strategy="trend_following", score=Decimal("7"), reason="r")
    )
    async with session_factory() as s:
        row = (await s.execute(select(SignalRow))).scalar_one()
    assert row.symbol == "BTCUSDT"
    assert row.direction == "LONG"
    assert row.score == "7"


async def test_log_command(session_factory):
    tl = TradeLogger(session_factory)
    await tl.log_command(command_id="c1", type="START_BOT", payload={"x": 1})
    assert await _count(session_factory, CommandLogRow) == 1


async def test_log_fill_and_position(session_factory):
    tl = TradeLogger(session_factory)
    await tl.log_fill(
        Fill(symbol="BTCUSDT", order_id="o1", side=Side.BUY,
             price=Decimal("100.5"), qty=Decimal("2"), fee=Decimal("0.1"))
    )
    await tl.log_position(
        Position(symbol="BTCUSDT", side=PositionSide.LONG, status=PositionStatus.ACTIVE,
                 qty=Decimal("2"), avg_entry_price=Decimal("100.5"),
                 stop_loss_price=Decimal("99"), entry_mode=EntryMode.BREAKOUT_CONFIRM)
    )
    assert await _count(session_factory, FillRow) == 1
    async with session_factory() as s:
        prow = (await s.execute(select(PositionRow))).scalar_one()
    assert prow.qty == "2"
    assert prow.avg_entry_price == "100.5"
    assert prow.entry_mode == "BREAKOUT_CONFIRM"


async def test_log_trade_truncates_long_r_multiple(session_factory):
    tl = TradeLogger(session_factory)
    await tl.log_trade(
        symbol="OPUSDT",
        side="SHORT",
        qty="920.7",
        entry_price="0.10251",
        exit_price="0.10247777",
        realized_pnl="0.029674161",
        exit_reason="SCENARIO_INVALID",
        r_multiple="0.08930531871733813705807884296",
    )
    async with session_factory() as s:
        row = (await s.execute(select(TradeRow))).scalar_one()
    assert row.r_multiple == "0.08930531871733"
