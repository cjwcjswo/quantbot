"""PAPER end-to-end: signal -> entry -> risk -> paper fill -> manage -> exit -> DB.

Drives PaperTradingService through the full pipeline with a healthy-breakout
dataset, then walks the price up (partial TP + trailing) and back down to a
trailing-stop exit, asserting positions and DB persistence (impl doc §20).
"""

from decimal import Decimal

from sqlalchemy import func, select

from apps.bot.runtime.runtime_state import RuntimeState
from apps.bot.workers.trading_pipeline import PaperExecutor, TradingService
from packages.core.enums import BotMode, PositionStatus
from packages.core.events import BotEventType
from packages.entry import EntryTimingEngine
from packages.execution import PaperExecutionEngine
from packages.messaging import EventBus
from packages.position import PositionManager
from packages.risk import RiskManager
from packages.signal import SignalEngine
from packages.storage import (
    BotEventRow,
    FillRow,
    PositionRow,
    SignalRow,
    TradeLogger,
    TradeRow,
)
from packages.strategy import StrategyRegistry, TrendFollowingStrategy
from tests.fakes.builders import candle, symbol_meta
from tests.fakes.builders import indicator_snapshot as snap


def _snapshots():
    return {
        "15": snap(timeframe="15", close="100", ema20="99", ema50="98",
                   slope="0.2", atr="1", atr_percent="1.5"),
        "5": snap(timeframe="5", close="100.5", ema20="100", ema50="99",
                  rsi="60", atr="1", atr_percent="1.5", volume_ratio="1.0"),
        "1": snap(timeframe="1", close="101", ema20="100.5", atr="1",
                  rsi="60", volume_ratio="2.0"),
    }


def _breakout_candles():
    flats = [candle(interval="1", open_time_ms=i * 60_000, o="100", h="100.2",
                    l="99.8", c="100") for i in range(5)]
    breakout = candle(interval="1", o="100.2", h="101.1", l="100.0", c="101.0")
    return flats + [breakout]


def _service(config, session_factory):
    registry = StrategyRegistry()
    registry.register(TrendFollowingStrategy(config))
    state = RuntimeState()
    tl = TradeLogger(session_factory)
    bus = EventBus(redis=None, sink=tl)  # events persist to bot_events
    service = TradingService(
        config,
        mode=BotMode.PAPER,
        signal_engine=SignalEngine(registry),
        entry_engine=EntryTimingEngine(config),
        risk_manager=RiskManager(config),
        position_manager=PositionManager(config),
        state=state,
        executor=PaperExecutor(PaperExecutionEngine(config)),
        trade_logger=tl,
        event_bus=bus,
    )
    return service, state


async def _count(session_factory, model) -> int:
    async with session_factory() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


async def test_paper_entry_and_trailing_exit(config, session_factory):
    service, state = _service(config, session_factory)

    pos = await service.evaluate_entry(
        symbol="BTCUSDT",
        snapshots=_snapshots(),
        candles_1m=_breakout_candles(),
        box_high=Decimal("100"),
        box_low=Decimal("98"),
        symbol_meta=symbol_meta(symbol="BTCUSDT", min_qty="0.001"),
        equity=Decimal("10000"),
        entry_price=Decimal("101"),
        best_bid=Decimal("100.98"),
        best_ask=Decimal("101.0"),
    )

    # --- entry happened and position is ACTIVE with virtual SL/TP ---
    assert pos is not None
    assert pos.status == PositionStatus.ACTIVE
    assert pos.qty == Decimal("30.000")
    assert pos.stop_loss_price == Decimal("100")
    assert pos.take_profit_price == Decimal("103")
    assert state.get_position("BTCUSDT") is pos
    assert await _count(session_factory, SignalRow) == 1
    assert await _count(session_factory, PositionRow) >= 1

    # --- price runs to +2R: partial take-profit + trailing ---
    up = candle(interval="1", o="102", h="103.2", l="102", c="103.2")
    actions1 = await service.manage(
        symbol="BTCUSDT", price=Decimal("103.2"), atr=Decimal("1"),
        best_bid=Decimal("103.1"), best_ask=Decimal("103.2"), candle_1m=up,
    )
    assert any(a.type.value == "PARTIAL_TP" for a in actions1)
    assert pos.qty == Decimal("15.000")  # 50% reduced
    assert pos.status == PositionStatus.ACTIVE

    # --- price falls below the trailing stop: full exit ---
    down = candle(interval="1", o="102", h="103.2", l="101", c="101")
    actions2 = await service.manage(
        symbol="BTCUSDT", price=Decimal("101.0"), atr=Decimal("1"),
        best_bid=Decimal("100.9"), best_ask=Decimal("101.1"), candle_1m=down,
    )
    assert any(a.type.value == "EXIT" for a in actions2)
    assert pos.status == PositionStatus.CLOSED
    assert pos.realized_pnl > 0  # net winner across the round trip

    # --- everything was persisted ---
    assert await _count(session_factory, FillRow) == 3  # entry + partial + exit
    assert await _count(session_factory, TradeRow) >= 1
    async with session_factory() as s:
        event_types = {
            r.type for r in (await s.execute(select(BotEventRow))).scalars()
        }
    assert BotEventType.POSITION_OPENED.value in event_types
    assert BotEventType.POSITION_CLOSED.value in event_types


async def test_no_entry_when_paused(config, session_factory):
    service, state = _service(config, session_factory)
    state.pause_new_entries(60)
    pos = await service.evaluate_entry(
        symbol="BTCUSDT",
        snapshots=_snapshots(),
        candles_1m=_breakout_candles(),
        box_high=Decimal("100"),
        box_low=Decimal("98"),
        symbol_meta=symbol_meta(symbol="BTCUSDT"),
        equity=Decimal("10000"),
        entry_price=Decimal("101"),
        best_bid=Decimal("100.98"),
        best_ask=Decimal("101.0"),
    )
    assert pos is None
