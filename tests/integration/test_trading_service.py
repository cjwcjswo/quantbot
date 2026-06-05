"""Guard gating + LIVE entry/protection through TradingService (impl doc §2.1, §5, §16)."""

from decimal import Decimal

from apps.bot.runtime.bot_state_machine import BotStateMachine
from apps.bot.runtime.runtime_state import RuntimeState
from apps.bot.workers.trading_pipeline import (
    CloseResult,
    GuardSet,
    LiveExecutor,
    MarketContext,
    PaperExecutor,
    TradingService,
)
from packages.core.enums import BotMode, BotState, PositionStatus
from packages.core.enums import EntryMode, PositionSide, PositionSource, SignalDirection
from packages.core.models import ExchangePosition, Position
from packages.core.models import OrderBook, OrderBookLevel
from packages.entry import EntryTimingEngine
from packages.execution import OrderManager, PaperExecutionEngine
from packages.guards import (
    ClockSyncGuard,
    DataQualityGuard,
    FundingGuard,
    PreOrderCheck,
)
from packages.messaging import EventBus
from packages.position import CooldownTracker, PositionManager, PositionProtectionManager
from packages.reconciliation import ManualInterventionHandler, ReconciliationManager
from packages.risk import RiskManager
from packages.signal import SignalEngine
from packages.strategy import StrategyRegistry, TrendFollowingStrategy
from tests.fakes import FakeGateway
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


def _candles():
    flats = [candle(interval="1", open_time_ms=i * 60_000, o="100", h="100.2",
                    l="99.8", c="100") for i in range(5)]
    return flats + [candle(interval="1", o="100.2", h="101.1", l="100.0", c="101.0")]


def _short_retest_snapshots():
    return {
        "15": snap(timeframe="15", close="98", ema20="99", ema50="101",
                   slope="-0.2", atr="1", atr_percent="1.5"),
        "5": snap(timeframe="5", close="98.5", ema20="99", ema50="101",
                  rsi="40", atr="1", atr_percent="1.5", volume_ratio="1.0"),
        "1": snap(timeframe="1", close="99.98", ema20="100.5", atr="1",
                  atr_percent="0.41", rsi="40", volume_ratio="2.0"),
    }


def _short_retest_candles():
    flats = [
        candle(interval="1", open_time_ms=i * 60_000, o="100", h="100.2",
               l="99.8", c="100")
        for i in range(4)
    ]
    return flats + [
        candle(interval="1", o="100.1", h="101.7", l="97.8", c="99.98")
    ]


def _make_service(
    config, *, mode, executor, guards=None, protection=None, events=None, state=None
):
    registry = StrategyRegistry()
    registry.register(TrendFollowingStrategy(config))
    bus = EventBus(redis=None, sink=events) if events is not None else None
    return TradingService(
        config, mode=mode,
        signal_engine=SignalEngine(registry),
        entry_engine=EntryTimingEngine(config),
        risk_manager=RiskManager(config),
        position_manager=PositionManager(config),
        state=state or RuntimeState(),
        executor=executor,
        guards=guards,
        protection_manager=protection,
        event_bus=bus,
    )


def _entry_kwargs(market=None):
    return dict(
        symbol="BTCUSDT", snapshots=_snapshots(), candles_1m=_candles(),
        box_high=Decimal("100"), box_low=Decimal("98"),
        symbol_meta=symbol_meta(symbol="BTCUSDT", min_qty="0.001"),
        equity=Decimal("10000"), entry_price=Decimal("101"),
        best_bid=Decimal("100.98"), best_ask=Decimal("101.0"), market=market,
    )


def _deep_book():
    return OrderBook(
        symbol="BTCUSDT",
        bids=(OrderBookLevel(price=Decimal("100.98"), size=Decimal("1000")),),
        asks=(OrderBookLevel(price=Decimal("101.0"), size=Decimal("1000")),),
    )


async def _paper_service(config, guards=None, events=None):
    return _make_service(
        config, mode=BotMode.PAPER,
        executor=PaperExecutor(PaperExecutionEngine(config)),
        guards=guards, events=events,
    )


# --- guard gating ---------------------------------------------------------- #
async def test_blocked_when_not_running(config):
    sm = BotStateMachine(initial=BotState.STANDBY)
    service = await _paper_service(config, guards=GuardSet(state_machine=sm))
    assert await service.evaluate_entry(**_entry_kwargs()) is None


async def test_blocked_by_data_quality(config):
    guards = GuardSet(data_quality=DataQualityGuard(config.data_quality))
    service = await _paper_service(config, guards=guards)
    market = MarketContext(
        now_ms=100_000,
        last_kline_ms=100_000 - (config.data_quality.max_kline_delay_sec + 1) * 1000,
        last_ticker_ms=100_000, last_orderbook_ms=100_000,
        ticker_price=Decimal("101"), kline_close=Decimal("101"),
    )
    assert await service.evaluate_entry(**_entry_kwargs(market)) is None


async def test_blocked_by_funding_window(config):
    guards = GuardSet(funding_guard=FundingGuard(config.funding_guard))
    service = await _paper_service(config, guards=guards)
    market = MarketContext(now_ms=0, next_funding_time_ms=5 * 60_000)
    assert await service.evaluate_entry(**_entry_kwargs(market)) is None


async def test_blocked_by_symbol_cooldown(config):
    cd = CooldownTracker(config.cooldown)
    from packages.core.enums import EntryMode
    cd.record_result("BTCUSDT", EntryMode.BREAKOUT_CONFIRM, is_win=False)
    service = await _paper_service(config, guards=GuardSet(cooldown=cd))
    assert await service.evaluate_entry(**_entry_kwargs()) is None


async def test_blocked_by_pre_order_depth(config):
    clock = ClockSyncGuard(block_trading_if_drift_ms_above=1000)
    clock.update(server_time_ms=0, local_time_ms=0)
    guards = GuardSet(pre_order_check=PreOrderCheck(config), clock_guard=clock)
    service = await _paper_service(config, guards=guards)
    thin = OrderBook(
        symbol="BTCUSDT",
        bids=(OrderBookLevel(price=Decimal("100.98"), size=Decimal("1")),),
        asks=(OrderBookLevel(price=Decimal("101.0"), size=Decimal("1")),),
    )
    market = MarketContext(orderbook=thin, symbol_status="Trading")
    assert await service.evaluate_entry(**_entry_kwargs(market)) is None


async def test_no_entry_reason_logged_for_pre_order_depth(config, events):
    clock = ClockSyncGuard(block_trading_if_drift_ms_above=1000)
    clock.update(server_time_ms=0, local_time_ms=0)
    guards = GuardSet(pre_order_check=PreOrderCheck(config), clock_guard=clock)
    service = await _paper_service(config, guards=guards, events=events)
    thin = OrderBook(
        symbol="BTCUSDT",
        bids=(OrderBookLevel(price=Decimal("100.98"), size=Decimal("1")),),
        asks=(OrderBookLevel(price=Decimal("101.0"), size=Decimal("1")),),
    )
    market = MarketContext(orderbook=thin, symbol_status="Trading")

    assert await service.evaluate_entry(**_entry_kwargs(market)) is None

    from packages.core.events import BotEventType
    no_entry = events.of_type(BotEventType.NO_ENTRY_REASON)
    assert len(no_entry) == 1
    assert no_entry[0].data["reason_code"] == "PRE_ORDER_INSUFFICIENT_DEPTH"
    assert no_entry[0].data["entry_mode_candidate"] == "BREAKOUT_CONFIRM"


async def test_orderbook_loaded_only_after_entry_candidate(config):
    clock = ClockSyncGuard(block_trading_if_drift_ms_above=1000)
    clock.update(server_time_ms=0, local_time_ms=0)
    guards = GuardSet(pre_order_check=PreOrderCheck(config), clock_guard=clock)
    service = await _paper_service(config, guards=guards)
    calls = {"n": 0}

    async def load_orderbook():
        calls["n"] += 1
        return _deep_book(), 100_000

    pos = await service.evaluate_entry(
        **_entry_kwargs(MarketContext(symbol_status="Trading")),
        orderbook_provider=load_orderbook,
    )

    assert pos is not None
    assert calls["n"] == 1


async def test_orderbook_not_loaded_without_signal(config):
    clock = ClockSyncGuard(block_trading_if_drift_ms_above=1000)
    clock.update(server_time_ms=0, local_time_ms=0)
    guards = GuardSet(pre_order_check=PreOrderCheck(config), clock_guard=clock)
    service = await _paper_service(config, guards=guards)
    calls = {"n": 0}
    snapshots = _snapshots()
    snapshots["5"] = snap(
        timeframe="5",
        close="100",
        ema20="100",
        ema50="100",
        rsi="60",
        atr="1",
        atr_percent="1.5",
        volume_ratio="1.0",
    )

    async def load_orderbook():
        calls["n"] += 1
        return _deep_book(), 100_000

    kwargs = _entry_kwargs(MarketContext(symbol_status="Trading"))
    kwargs["snapshots"] = snapshots
    assert await service.evaluate_entry(
        **kwargs,
        orderbook_provider=load_orderbook,
    ) is None
    assert calls["n"] == 0


async def test_paper_entry_passes_with_no_guards(config):
    service = await _paper_service(config)
    pos = await service.evaluate_entry(**_entry_kwargs())
    assert pos is not None
    assert pos.status == PositionStatus.ACTIVE


# --- LIVE entry + TP/SL protection ----------------------------------------- #
async def _noop_sleep(_):
    return None


async def test_live_entry_protected_then_active(config, events):
    config.bot.mode = BotMode.LIVE
    gw = FakeGateway()
    gw.fill_ratio = Decimal("1")
    om = OrderManager(gw, config)
    bus = EventBus(redis=None, sink=events)
    ppm = PositionProtectionManager(gw, om, bus, config, sleep=_noop_sleep)
    service = _make_service(
        config, mode=BotMode.LIVE, executor=LiveExecutor(gw, om),
        protection=ppm, events=events,
    )
    pos = await service.evaluate_entry(**_entry_kwargs())
    assert pos is not None
    assert pos.status == PositionStatus.ACTIVE
    assert service._state.get_position("BTCUSDT") is pos
    assert gw.leverage.get("BTCUSDT") is not None  # leverage was set before entry
    assert gw.placed_orders[0].stop_loss == pos.stop_loss_price
    assert gw.trading_stops == []
    from packages.core.events import BotEventType
    assert BotEventType.TPSL_VERIFIED in events.types()


async def test_live_retest_exchange_sl_uses_selected_structure_stop(config, events):
    config.bot.mode = BotMode.LIVE
    gw = FakeGateway()
    gw.fill_ratio = Decimal("1")
    om = OrderManager(gw, config)
    bus = EventBus(redis=None, sink=events)
    ppm = PositionProtectionManager(gw, om, bus, config, sleep=_noop_sleep)
    service = _make_service(
        config, mode=BotMode.LIVE, executor=LiveExecutor(gw, om),
        protection=ppm, events=events,
    )
    service._entry.retests.register(
        "BTCUSDT", SignalDirection.SHORT, Decimal("100")
    )

    pos = await service.evaluate_entry(
        symbol="BTCUSDT",
        snapshots=_short_retest_snapshots(),
        candles_1m=_short_retest_candles(),
        box_high=Decimal("102"),
        box_low=Decimal("100"),
        symbol_meta=symbol_meta(symbol="BTCUSDT", min_qty="0.001"),
        equity=Decimal("10000"),
        entry_price=Decimal("100"),
        best_bid=Decimal("99.98"),
        best_ask=Decimal("100.0"),
    )

    assert pos is not None
    assert pos.entry_mode == EntryMode.RETEST_CONFIRM
    assert pos.stop_loss_price == Decimal("101.8")
    assert gw.placed_orders[0].stop_loss == Decimal("101.8")
    assert gw.trading_stops == []
    from packages.core.events import BotEventType
    opened = events.of_type(BotEventType.POSITION_OPENED)[0]
    assert opened.data["selected_stop_price"] == "101.8"
    assert opened.data["structure_stop_price"] == "101.8"
    assert opened.data["resolved_stop_atr"] == "1.3"


async def test_live_entry_blocked_when_tpsl_fails(config, events):
    config.bot.mode = BotMode.LIVE
    gw = FakeGateway()
    gw.fill_ratio = Decimal("1")
    gw.disable_tpsl = True  # verify fails -> emergency close, not ACTIVE
    om = OrderManager(gw, config)
    bus = EventBus(redis=None, sink=events)
    ppm = PositionProtectionManager(gw, om, bus, config, sleep=_noop_sleep)
    service = _make_service(
        config, mode=BotMode.LIVE, executor=LiveExecutor(gw, om),
        protection=ppm, events=events,
    )
    pos = await service.evaluate_entry(**_entry_kwargs())
    assert pos is None  # never became ACTIVE
    assert service._state.get_position("BTCUSDT").status == PositionStatus.CLOSED
    from packages.core.events import BotEventType
    assert BotEventType.EMERGENCY_TPSL_FAILED in events.types()


async def test_tpsl_failure_moves_state_to_order_locked(config, events):
    config.bot.mode = BotMode.LIVE
    gw = FakeGateway()
    gw.fill_ratio = Decimal("1")
    gw.disable_tpsl = True
    sm = BotStateMachine(initial=BotState.RUNNING)
    om = OrderManager(gw, config)
    bus = EventBus(redis=None, sink=events)
    ppm = PositionProtectionManager(gw, om, bus, config, sleep=_noop_sleep)
    service = _make_service(
        config, mode=BotMode.LIVE, executor=LiveExecutor(gw, om),
        protection=ppm, events=events,
        guards=GuardSet(state_machine=sm),
    )
    assert await service.evaluate_entry(**_entry_kwargs()) is None
    assert sm.state == BotState.ORDER_LOCKED


async def test_manage_reduces_position_on_extreme_funding(config):
    paper = PaperExecutionEngine(config)
    service = _make_service(
        config, mode=BotMode.PAPER, executor=PaperExecutor(paper),
        guards=GuardSet(funding_guard=FundingGuard(config.funding_guard)),
    )
    paper._net["BTCUSDT"] = (Decimal("10"), Decimal("100"))
    pos = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.ACTIVE,
        source=PositionSource.BOT,
        qty=Decimal("10"),
        avg_entry_price=Decimal("100"),
        initial_risk_per_unit=Decimal("1"),
        stop_loss_price=Decimal("99"),
        take_profit_price=Decimal("102"),
        entry_mode=EntryMode.BREAKOUT_CONFIRM,
    )
    service._state.positions["BTCUSDT"] = pos
    await service.manage(
        symbol="BTCUSDT",
        price=Decimal("100"),
        atr=Decimal("1"),
        best_bid=Decimal("100"),
        best_ask=Decimal("100.1"),
        funding_rate=Decimal("0.0012"),
    )
    assert pos.qty == Decimal("5.0")


async def test_close_settlement_does_not_trigger_manual_mismatch(config, events):
    state = RuntimeState()
    gw = FakeGateway()
    bus = EventBus(redis=None, sink=events)
    handler = ManualInterventionHandler(state, bus, config.manual_intervention)
    recon = ReconciliationManager(gw, state, handler, bus, config.reconciliation)

    class ReconcileDuringCloseExecutor:
        async def open(self, **_kwargs):  # pragma: no cover - not used here
            raise AssertionError("open should not be called")

        async def close(self, **_kwargs):
            gw.set_position(
                ExchangePosition(
                    symbol="NEARUSDT",
                    side=PositionSide.SHORT,
                    size=Decimal("16.9"),
                    avg_price=Decimal("1.943"),
                )
            )
            result = await recon.reconcile_once()
            assert result.qty_mismatches == []
            return CloseResult(
                fill_qty=Decimal("16.8"),
                fill_price=Decimal("1.94747619"),
                fee=Decimal("0"),
                realized=Decimal("-0.075199992"),
            )

    pos = Position(
        symbol="NEARUSDT",
        side=PositionSide.SHORT,
        status=PositionStatus.ACTIVE,
        source=PositionSource.BOT,
        qty=Decimal("33.7"),
        avg_entry_price=Decimal("1.943"),
        stop_loss_price=Decimal("1.9529"),
        take_profit_price=Decimal("1.9232"),
        entry_mode=EntryMode.PRE_BREAKOUT_SCOUT,
    )
    state.positions[pos.symbol] = pos
    service = _make_service(
        config,
        mode=BotMode.LIVE,
        executor=ReconcileDuringCloseExecutor(),
        events=events,
        state=state,
    )

    ok = await service.close_position(
        "NEARUSDT",
        best_bid=Decimal("1.9474"),
        best_ask=Decimal("1.9475"),
        close_percent=Decimal("50"),
    )

    assert ok is True
    assert pos.qty == Decimal("16.9")
    assert pos.manual_added_qty == Decimal("0")
    assert not state.new_entries_paused()
    from packages.core.events import BotEventType
    assert BotEventType.MANUAL_PARTIAL_CLOSE_DETECTED not in events.types()
