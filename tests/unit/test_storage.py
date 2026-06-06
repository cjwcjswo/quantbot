"""Tests for storage models + TradeLogger persistence (arch doc §7)."""

from decimal import Decimal

from sqlalchemy import func, select

from packages.core.enums import (
    EntryMode,
    OrderStatus,
    OrderType,
    PositionSide,
    PositionStatus,
    Side,
    SignalDirection,
)
from packages.core.events import BotEvent, BotEventType
from packages.core.models import Fill, Order, Position, Signal
from packages.storage import (
    BotEventRow,
    CommandLogRow,
    FillRow,
    OrderRow,
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
    await tl(BotEvent(type=BotEventType.ORDER_FAILED, symbol="BTCUSDT", message="x"))
    assert await _count(session_factory, BotEventRow) == 1
    async with session_factory() as s:
        row = (await s.execute(select(BotEventRow))).scalar_one()
    assert row.severity == "ERROR"


async def test_event_sink_persists_important_info(session_factory):
    tl = TradeLogger(session_factory)
    await tl(BotEvent(type=BotEventType.POSITION_OPENED, symbol="BTCUSDT", message="x"))
    await tl(BotEvent(type=BotEventType.NO_ENTRY_REASON, symbol="ETHUSDT", message="SCOUT_SCORE_TOO_LOW"))
    assert await _count(session_factory, BotEventRow) == 2
    async with session_factory() as s:
        rows = (await s.execute(select(BotEventRow).order_by(BotEventRow.id))).scalars().all()
    assert [row.severity for row in rows] == ["INFO", "INFO"]


async def test_event_sink_persists_position_opened_info(session_factory):
    tl = TradeLogger(session_factory)
    await tl(BotEvent(type=BotEventType.POSITION_OPENED, symbol="BTCUSDT", message="x"))
    assert await _count(session_factory, BotEventRow) == 1
    async with session_factory() as s:
        row = (await s.execute(select(BotEventRow))).scalar_one()
    assert row.severity == "INFO"


async def test_event_sink_skips_noisy_info(session_factory):
    tl = TradeLogger(session_factory)
    await tl(BotEvent(type=BotEventType.SIGNAL, symbol="BTCUSDT", message="noise"))
    await tl(BotEvent(type=BotEventType.DATA_QUALITY_BLOCK, symbol="ETHUSDT", message="noise"))
    await tl(BotEvent(type=BotEventType.RECONCILED, message="noise"))
    assert await _count(session_factory, BotEventRow) == 0


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


async def test_log_closed_position_closes_previous_open_snapshots(session_factory):
    tl = TradeLogger(session_factory)
    await tl.log_order(
        Order(
            symbol="BTCUSDT",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            qty=Decimal("1"),
            price=Decimal("99"),
            status=OrderStatus.NEW,
            client_order_id="sl-1",
            reduce_only=True,
        ),
        mode="LIVE",
        source="BOT",
    )
    pos = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.ACTIVE,
        qty=Decimal("1"),
        avg_entry_price=Decimal("100"),
    )
    await tl.log_position(pos, mode="LIVE")
    pos.qty = Decimal("0.5")
    await tl.log_position(pos, mode="LIVE")

    pos.status = PositionStatus.CLOSED
    pos.qty = Decimal("0")
    await tl.log_position(pos, mode="LIVE")

    async with session_factory() as s:
        rows = (await s.execute(
            select(PositionRow).where(PositionRow.symbol == "BTCUSDT")
        )).scalars().all()
        order = (
            await s.execute(
                select(OrderRow).where(OrderRow.client_order_id == "sl-1")
            )
        ).scalar_one()

    assert len(rows) == 3
    assert {row.status for row in rows} == {"CLOSED"}
    assert {row.qty for row in rows} == {"0"}
    assert order.status == "CANCELLED"


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
