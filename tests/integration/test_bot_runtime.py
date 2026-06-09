"""BotRuntime lifecycle tests with injected fakeredis + FakeGateway."""

from decimal import Decimal

import fakeredis.aioredis
import pytest

from apps.bot.runtime import BotRuntime
from packages.config import load_app_config
from packages.config.settings import Secrets
from packages.core.enums import (
    BotMode,
    BotState,
    EntryMode,
    OrderStatus,
    OrderType,
    PositionSide,
    PositionSource,
    PositionStatus,
    Side,
)
from packages.core.errors import RuntimeLockError
from packages.core.models import ExchangePosition, Order, Position
from packages.messaging import (
    Command,
    CommandQueue,
    CommandType,
    state_keys,
)
from packages.storage import TradeLogger
from tests.fakes import FakeGateway
from tests.fakes.builders import candle, series_from_closes, symbol_meta, ticker


def _runtime(redis, gateway=None, *, mode=None):
    cfg = load_app_config("config/quantbot.yaml")
    if mode is not None:
        cfg.bot.mode = mode
    secrets = Secrets()
    return BotRuntime(cfg, secrets, redis=redis, gateway=gateway or FakeGateway())


def _runtime_with_config(redis, config_path, gateway=None):
    cfg = load_app_config(config_path)
    secrets = Secrets(quantbot_config=str(config_path))
    return BotRuntime(cfg, secrets, redis=redis, gateway=gateway or FakeGateway())


async def test_boots_to_standby_not_running(redis):
    rt = _runtime(redis)
    await rt.startup()
    assert rt.state_machine.state == BotState.STANDBY
    assert not rt.state_machine.can_enter_new_position()
    # mode + status published to Redis
    assert await redis.get(state_keys.BOT_MODE) == "LIVE"
    assert await redis.get(state_keys.BOT_STATUS) == "STANDBY"
    await rt.shutdown()


async def test_start_command_drives_to_running(redis):
    rt = _runtime(redis)
    await rt.startup()
    await rt.handle_command(Command(type=CommandType.START_BOT))
    assert rt.state_machine.state == BotState.RUNNING
    assert rt.state_machine.can_enter_new_position()
    await rt.shutdown()


async def test_pause_and_resume(redis):
    rt = _runtime(redis)
    await rt.startup()
    await rt.handle_command(Command(type=CommandType.START_BOT))
    await rt.handle_command(Command(type=CommandType.PAUSE_TRADING))
    assert rt.state_machine.state == BotState.PAUSED
    await rt.handle_command(Command(type=CommandType.RESUME_TRADING))
    assert rt.state_machine.state == BotState.RUNNING
    await rt.shutdown()


async def test_second_instance_lock_fails(redis_server):
    r1 = fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)
    r2 = fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)
    rt1 = _runtime(r1)
    rt2 = _runtime(r2)
    await rt1.startup()
    with pytest.raises(RuntimeLockError):
        await rt2.startup()
    await rt1.shutdown()


async def test_stop_command_requests_shutdown(redis):
    rt = _runtime(redis)
    await rt.startup()
    await rt.handle_command(Command(type=CommandType.STOP_BOT))
    assert rt._shutdown.is_set()
    await rt.shutdown()
    assert rt.state_machine.state == BotState.STOPPED


async def test_trading_graph_built_on_startup(redis):
    rt = _runtime(redis)
    await rt.startup()
    assert rt._trading is not None
    # empty universe (FakeGateway has no instruments) => nothing to watch, no crash
    assert rt._watch_symbols() == []
    await rt.shutdown()


async def test_startup_restores_persisted_bot_position_before_reconcile(
    redis, session_factory
):
    tl = TradeLogger(session_factory)
    await tl.log_position(
        Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            status=PositionStatus.ACTIVE,
            source=PositionSource.BOT,
            qty=Decimal("1"),
            avg_entry_price=Decimal("100"),
            stop_loss_price=Decimal("98"),
            entry_mode=EntryMode.PRE_BREAKOUT_SCOUT,
        ),
        mode="LIVE",
        strategy_id="trend_following",
    )
    gw = FakeGateway()
    gw.set_position(
        ExchangePosition(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            size=Decimal("1"),
            avg_price=Decimal("100"),
            leverage=Decimal("1"),
            stop_loss=Decimal("98"),
        )
    )
    rt = _runtime(redis, gw, mode=BotMode.LIVE)
    rt._trade_logger = tl

    await rt.startup()

    restored = rt.runtime_state.positions["BTCUSDT"]
    assert restored.source == PositionSource.BOT
    assert restored.initial_risk_per_unit == Decimal("2")
    assert rt._last_reconciliation_status.get("external_positions") == []
    await rt.shutdown()


async def test_scanner_refresh_populates_runtime_watchlist(redis):
    gw = FakeGateway()
    gw.set_instruments([symbol_meta(symbol="BTCUSDT", launch_time_ms=0)])
    gw.set_ticker(ticker(symbol="BTCUSDT", turnover_24h="100000000"))
    gw.set_kline(
        "BTCUSDT",
        "15",
        series_from_closes(["100"] * 80, symbol="BTCUSDT", interval="15"),
    )
    rt = _runtime(redis, gw, mode=BotMode.PAPER)
    await rt.startup()
    await rt._collector.refresh_tickers()
    await rt._refresh_watchlist_if_due(force=True)
    assert rt._watch_symbols() == ["BTCUSDT"]
    await rt.shutdown()


async def test_empty_scanner_watchlist_does_not_fallback_to_universe(redis):
    gw = FakeGateway()
    gw.set_instruments(
        [
            symbol_meta(symbol="1000PEPEUSDT", launch_time_ms=0),
            symbol_meta(symbol="BTCUSDT", launch_time_ms=0),
        ]
    )
    rt = _runtime(redis, gw, mode=BotMode.PAPER)
    await rt.startup()
    await rt._universe.refresh()

    rt._watchlist = []
    assert rt._watch_symbols() == []

    rt.runtime_state.positions["BTCUSDT"] = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.ACTIVE,
        source=PositionSource.BOT,
        qty=Decimal("1"),
        avg_entry_price=Decimal("100"),
        stop_loss_price=Decimal("99"),
        take_profit_price=Decimal("102"),
        initial_risk_per_unit=Decimal("1"),
        entry_mode=EntryMode.BREAKOUT_CONFIRM,
    )
    assert rt._watch_symbols() == ["BTCUSDT"]
    await rt.shutdown()


async def test_scanner_refresh_prefilters_before_kline_atr(redis):
    gw = FakeGateway()
    symbols = [f"SYM{i}USDT" for i in range(10)]
    gw.set_instruments([symbol_meta(symbol=s, launch_time_ms=0) for s in symbols])
    for i, symbol in enumerate(symbols):
        gw.set_ticker(
            ticker(
                symbol=symbol,
                bid="100",
                ask="100.01",
                turnover_24h=str(100_000_000 - i),
            )
        )
        gw.set_kline(
            symbol,
            "15",
            series_from_closes(["100"] * 80, symbol=symbol, interval="15"),
        )
    rt = _runtime(redis, gw, mode=BotMode.PAPER)
    rt.config.scanner.max_candidates = 2
    await rt.startup()
    await rt._collector.refresh_tickers()

    await rt._refresh_watchlist_if_due(force=True)

    assert len(gw.kline_calls) == 6
    assert [symbol for symbol, _, _ in gw.kline_calls] == symbols[:6]
    assert [tf for _, tf, _ in gw.kline_calls] == ["15"] * 6
    await rt.shutdown()


async def test_scanner_atr_cache_prunes_stale_and_ineligible_symbols(redis):
    rt = _runtime(redis, mode=BotMode.PAPER)
    rt.config.scanner.atr_cache_ttl_sec = 10
    rt._scanner_atr_percent = {
        "FRESHUSDT": Decimal("1.0"),
        "STALEUSDT": Decimal("1.0"),
        "OUTSIDEUSDT": Decimal("1.0"),
    }
    rt._scanner_atr_updated_ms = {
        "FRESHUSDT": 20_000,
        "STALEUSDT": 1_000,
        "OUTSIDEUSDT": 20_000,
    }

    fresh = rt._fresh_scanner_atr(
        [ticker(symbol="FRESHUSDT"), ticker(symbol="STALEUSDT")], 20_000
    )

    assert fresh == {"FRESHUSDT": Decimal("1.0")}
    assert set(rt._scanner_atr_percent) == {"FRESHUSDT"}


async def test_trading_cycle_publishes_watchlist(redis):
    import json

    gw = FakeGateway()
    gw.set_instruments([symbol_meta(symbol="BTCUSDT", launch_time_ms=0)])
    gw.set_ticker(ticker(symbol="BTCUSDT", bid="100", ask="100.1",
                         turnover_24h="100000000"))
    for tf in ("1", "5", "15"):
        gw.set_kline("BTCUSDT", tf,
                     series_from_closes(["100"] * 120, symbol="BTCUSDT", interval=tf))
    rt = _runtime(redis, gw, mode=BotMode.PAPER)
    await rt.startup()
    rt.state_machine.force(BotState.RUNNING, reason="test")
    await rt._trading_cycle()
    raw = await redis.get(state_keys.BOT_WATCHLIST)
    assert raw is not None
    entries = json.loads(raw)
    assert any(e["symbol"] == "BTCUSDT" for e in entries)
    # flat market => no firing signal, but the symbol is still surfaced
    btc = next(e for e in entries if e["symbol"] == "BTCUSDT")
    assert btc["direction"] in ("NONE", "LONG", "SHORT")
    assert "readiness" in btc
    assert gw.orderbook_calls == []
    await rt.shutdown()


async def test_process_symbol_refreshes_stale_tickers(redis):
    gw = FakeGateway()
    gw.set_instruments([symbol_meta(symbol="BTCUSDT", launch_time_ms=0)])
    gw.set_ticker(ticker(symbol="BTCUSDT", bid="100", ask="100.1",
                         turnover_24h="100000000"))
    for tf in ("1", "5", "15"):
        gw.set_kline("BTCUSDT", tf,
                     series_from_closes(["100"] * 120, symbol="BTCUSDT", interval=tf))
    rt = _runtime(redis, gw, mode=BotMode.PAPER)
    await rt.startup()
    await rt._universe.refresh()
    await rt._collector.refresh_tickers()
    rt._collector._last_ticker_ms = 0

    await rt._process_symbol("BTCUSDT", Decimal("10000"))

    assert gw.ticker_calls >= 2
    await rt.shutdown()


async def test_trading_loop_manages_open_positions_when_risk_locked(redis):
    rt = _runtime(redis, mode=BotMode.PAPER)
    rt.state_machine.force(BotState.RISK_LOCKED, reason="test")
    rt.runtime_state.positions["BTCUSDT"] = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.ACTIVE,
        source=PositionSource.BOT,
        qty=Decimal("1"),
        avg_entry_price=Decimal("100"),
        stop_loss_price=Decimal("99"),
        take_profit_price=Decimal("102"),
        initial_risk_per_unit=Decimal("1"),
        entry_mode=EntryMode.BREAKOUT_CONFIRM,
    )
    called = []

    async def fake_management_cycle():
        called.append(True)
        rt.request_shutdown()

    rt._management_cycle = fake_management_cycle

    await rt._trading_loop()

    assert called == [True]


async def test_management_cycle_does_not_evaluate_new_entries(redis):
    class CaptureTrading:
        def __init__(self):
            self.manage_calls = []

        async def update_post_exit_mfe(self, *args, **kwargs):
            return None

        async def manage(self, **kwargs):
            self.manage_calls.append(kwargs)
            return []

    gw = FakeGateway()
    gw.set_instruments([symbol_meta(symbol="BTCUSDT", launch_time_ms=0)])
    gw.set_ticker(ticker(symbol="BTCUSDT", bid="100", ask="100.1",
                         turnover_24h="100000000"))
    for tf in ("1", "5", "15"):
        gw.set_kline("BTCUSDT", tf,
                     series_from_closes(["100"] * 120, symbol="BTCUSDT", interval=tf))
    rt = _runtime(redis, gw, mode=BotMode.PAPER)
    await rt.startup()
    rt.state_machine.force(BotState.RISK_LOCKED, reason="test")
    rt.runtime_state.positions["BTCUSDT"] = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.ACTIVE,
        source=PositionSource.BOT,
        qty=Decimal("1"),
        avg_entry_price=Decimal("100"),
        stop_loss_price=Decimal("99"),
        take_profit_price=Decimal("102"),
        initial_risk_per_unit=Decimal("1"),
        entry_mode=EntryMode.BREAKOUT_CONFIRM,
    )
    capture = CaptureTrading()
    rt._trading = capture

    await rt._management_cycle()

    assert len(capture.manage_calls) == 1
    assert capture.manage_calls[0]["symbol"] == "BTCUSDT"
    assert gw.orderbook_calls == []
    await rt.shutdown()


async def test_process_symbol_passes_only_confirmed_candles_to_entry(redis):
    class CaptureTrading:
        def __init__(self):
            self.candles_1m = None

        async def update_post_exit_mfe(self, *args, **kwargs):
            return None

        async def evaluate_entry(self, **kwargs):
            self.candles_1m = kwargs["candles_1m"]
            return None

        def preview_watch(self, **kwargs):
            return {}

    gw = FakeGateway()
    gw.set_instruments([symbol_meta(symbol="BTCUSDT", launch_time_ms=0)])
    gw.set_ticker(ticker(symbol="BTCUSDT", bid="100", ask="100.1",
                         turnover_24h="100000000"))
    confirmed_1m = series_from_closes(
        ["100"] * 120, symbol="BTCUSDT", interval="1"
    )
    current_1m = candle(
        symbol="BTCUSDT", interval="1", open_time_ms=120 * 60_000,
        c="105", confirmed=False,
    )
    gw.set_kline("BTCUSDT", "1", confirmed_1m + [current_1m])
    for tf in ("5", "15"):
        gw.set_kline("BTCUSDT", tf,
                     series_from_closes(["100"] * 120, symbol="BTCUSDT", interval=tf))

    rt = _runtime(redis, gw, mode=BotMode.PAPER)
    await rt.startup()
    await rt._universe.refresh()
    await rt._collector.refresh_tickers()
    capture = CaptureTrading()
    rt._trading = capture

    await rt._process_symbol("BTCUSDT", Decimal("10000"))

    assert capture.candles_1m is not None
    assert all(c.confirmed for c in capture.candles_1m)
    assert capture.candles_1m[-1].open_time_ms != current_1m.open_time_ms
    await rt.shutdown()


async def test_process_symbol_entry_box_excludes_decision_candle(redis):
    class CaptureTrading:
        def __init__(self):
            self.kwargs = None

        async def update_post_exit_mfe(self, *args, **kwargs):
            return None

        async def evaluate_entry(self, **kwargs):
            self.kwargs = kwargs
            return None

        def preview_watch(self, **kwargs):
            return {}

    gw = FakeGateway()
    gw.set_instruments([symbol_meta(symbol="BTCUSDT", launch_time_ms=0)])
    gw.set_ticker(
        ticker(symbol="BTCUSDT", last="104", bid="103.9", ask="104.1",
               turnover_24h="100000000")
    )
    prior = [
        candle(
            symbol="BTCUSDT", interval="1", open_time_ms=i * 60_000,
            o="100", h="101", l="99", c="100",
        )
        for i in range(60)
    ]
    breakout = candle(
        symbol="BTCUSDT", interval="1", open_time_ms=60 * 60_000,
        o="100", h="106", l="99", c="104", v="2000",
    )
    gw.set_kline("BTCUSDT", "1", prior + [breakout])
    for tf in ("5", "15"):
        gw.set_kline(
            "BTCUSDT", tf,
            series_from_closes(["100"] * 120, symbol="BTCUSDT", interval=tf),
        )

    rt = _runtime(redis, gw, mode=BotMode.PAPER)
    await rt.startup()
    await rt._universe.refresh()
    await rt._collector.refresh_tickers()
    capture = CaptureTrading()
    rt._trading = capture

    await rt._process_symbol("BTCUSDT", Decimal("10000"))

    assert capture.kwargs is not None
    assert capture.kwargs["box_high"] == Decimal("101")
    assert capture.kwargs["box_low"] == Decimal("99")
    assert capture.kwargs["snapshots"]["1"].swing_high == Decimal("106")
    await rt.shutdown()


async def test_process_symbol_forces_kline_refresh_when_gap_is_pending(redis):
    class CaptureTrading:
        async def update_post_exit_mfe(self, *args, **kwargs):
            return None

        async def evaluate_entry(self, **kwargs):
            return None

        def preview_watch(self, **kwargs):
            return {}

    gw = FakeGateway()
    gw.set_instruments([symbol_meta(symbol="BTCUSDT", launch_time_ms=0)])
    gw.set_ticker(ticker(symbol="BTCUSDT", bid="100", ask="100.1",
                         turnover_24h="100000000"))
    for tf in ("1", "5", "15"):
        gw.set_kline(
            "BTCUSDT", tf,
            series_from_closes(["100"] * 120, symbol="BTCUSDT", interval=tf),
        )

    rt = _runtime(redis, gw, mode=BotMode.PAPER)
    await rt.startup()
    await rt._universe.refresh()
    await rt._collector.refresh_tickers()
    await rt._collector.refresh_klines("BTCUSDT", "1")
    for tf in ("5", "15"):
        await rt._collector.refresh_klines("BTCUSDT", tf)
    gw.kline_calls.clear()
    rt._collector.store._gaps[("BTCUSDT", "1")] = 2
    rt._trading = CaptureTrading()

    await rt._process_symbol("BTCUSDT", Decimal("10000"))

    assert ("BTCUSDT", "1", 200) in gw.kline_calls
    assert rt._collector.missing_candles("BTCUSDT", "1") == 0
    await rt.shutdown()


async def test_process_symbol_reuses_cached_higher_timeframe_klines(redis):
    class CaptureTrading:
        async def update_post_exit_mfe(self, *args, **kwargs):
            return None

        async def evaluate_entry(self, **kwargs):
            return None

        def preview_watch(self, **kwargs):
            return {}

    gw = FakeGateway()
    gw.set_instruments([symbol_meta(symbol="BTCUSDT", launch_time_ms=0)])
    gw.set_ticker(ticker(symbol="BTCUSDT", bid="100", ask="100.1",
                         turnover_24h="100000000"))
    for tf in ("1", "5", "15"):
        gw.set_kline("BTCUSDT", tf,
                     series_from_closes(["100"] * 120, symbol="BTCUSDT", interval=tf))

    rt = _runtime(redis, gw, mode=BotMode.PAPER)
    await rt.startup()
    await rt._universe.refresh()
    await rt._collector.refresh_tickers()
    await rt._collector.refresh_klines("BTCUSDT", "5")
    await rt._collector.refresh_klines("BTCUSDT", "15")
    gw.kline_calls.clear()
    rt._trading = CaptureTrading()

    await rt._process_symbol("BTCUSDT", Decimal("10000"))

    assert gw.kline_calls == [("BTCUSDT", "1", 200)]
    await rt.shutdown()


async def test_market_ws_starts_after_watchlist_and_updates_kline_freshness(redis):
    class WsGateway(FakeGateway):
        def __init__(self):
            super().__init__()
            self.ws_symbols = []
            self.stop_count = 0
            self.on_candle = None

        def start_market_websocket(self, *, symbols, on_candle=None, **_kwargs):
            self.ws_symbols.append(list(symbols))
            self.on_candle = on_candle

        def stop_market_websocket(self):
            self.stop_count += 1

    gw = WsGateway()
    rt = _runtime(redis, gw, mode=BotMode.PAPER)
    await rt.startup()

    rt._watchlist = ["BTCUSDT"]
    rt._start_market_ws()
    assert gw.ws_symbols[-1] == ["BTCUSDT"]

    gw.on_candle(candle(symbol="BTCUSDT", interval="1", open_time_ms=60_000))
    assert rt._collector.last_kline_ms("BTCUSDT", "1") is not None

    rt._watchlist = ["ETHUSDT"]
    rt._start_market_ws()
    assert gw.stop_count == 1
    assert gw.ws_symbols[-1] == ["ETHUSDT"]
    await rt.shutdown()


async def test_close_position_command_closes_bot_position(redis):
    gw = FakeGateway()
    gw.set_ticker(ticker(symbol="BTCUSDT", bid="100", ask="100.1"))
    rt = _runtime(redis, gw, mode=BotMode.PAPER)
    await rt.startup()
    rt.state_machine.force(BotState.RUNNING, reason="test")
    assert rt._paper_engine is not None
    rt._paper_engine._net["BTCUSDT"] = (Decimal("1"), Decimal("99"))
    rt.runtime_state.positions["BTCUSDT"] = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.ACTIVE,
        source=PositionSource.BOT,
        qty=Decimal("1"),
        avg_entry_price=Decimal("99"),
        stop_loss_price=Decimal("98"),
        take_profit_price=Decimal("101"),
        initial_risk_per_unit=Decimal("1"),
        entry_mode=EntryMode.BREAKOUT_CONFIRM,
    )
    await rt.handle_command(
        Command(type=CommandType.CLOSE_POSITION, payload={"symbol": "BTCUSDT"})
    )
    assert rt.runtime_state.positions["BTCUSDT"].status == PositionStatus.CLOSED
    await rt.shutdown()


async def test_close_position_command_respects_percent(redis):
    gw = FakeGateway()
    gw.set_ticker(ticker(symbol="BTCUSDT", bid="100", ask="100.1"))
    rt = _runtime(redis, gw, mode=BotMode.PAPER)
    await rt.startup()
    rt.state_machine.force(BotState.RUNNING, reason="test")
    assert rt._paper_engine is not None
    rt._paper_engine._net["BTCUSDT"] = (Decimal("1"), Decimal("99"))
    rt.runtime_state.positions["BTCUSDT"] = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.ACTIVE,
        source=PositionSource.BOT,
        qty=Decimal("1"),
        avg_entry_price=Decimal("99"),
        stop_loss_price=Decimal("98"),
        take_profit_price=Decimal("101"),
        initial_risk_per_unit=Decimal("1"),
        entry_mode=EntryMode.BREAKOUT_CONFIRM,
    )
    await rt.handle_command(
        Command(
            type=CommandType.CLOSE_POSITION,
            payload={"symbol": "BTCUSDT", "close_percent": 50},
        )
    )
    pos = rt.runtime_state.positions["BTCUSDT"]
    assert pos.status == PositionStatus.ACTIVE
    assert pos.qty == Decimal("0.5")
    await rt.shutdown()


async def test_stop_command_applies_cancel_and_close_options(redis):
    gw = FakeGateway()
    gw.set_ticker(ticker(symbol="BTCUSDT", bid="100", ask="100.1"))
    rt = _runtime(redis, gw, mode=BotMode.PAPER)
    await rt.startup()
    rt.state_machine.force(BotState.RUNNING, reason="test")
    assert rt._paper_engine is not None
    rt._paper_engine._net["BTCUSDT"] = (Decimal("1"), Decimal("99"))
    rt.runtime_state.positions["BTCUSDT"] = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.ACTIVE,
        source=PositionSource.BOT,
        qty=Decimal("1"),
        avg_entry_price=Decimal("99"),
        stop_loss_price=Decimal("98"),
        take_profit_price=Decimal("101"),
        initial_risk_per_unit=Decimal("1"),
        entry_mode=EntryMode.BREAKOUT_CONFIRM,
    )
    rt.runtime_state.orders["cid-1"] = Order(
        symbol="BTCUSDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        qty=Decimal("1"),
        client_order_id="cid-1",
        order_id="oid-1",
        status=OrderStatus.NEW,
    )
    await rt.handle_command(
        Command(
            type=CommandType.STOP_BOT,
            payload={"cancel_open_orders": True, "close_positions": True},
        )
    )
    assert gw.cancelled == [("BTCUSDT", "oid-1", "cid-1")]
    assert rt.runtime_state.orders["cid-1"].status == OrderStatus.CANCELLED
    assert rt.runtime_state.positions["BTCUSDT"].status == PositionStatus.CLOSED
    assert rt._shutdown.is_set()
    await rt.shutdown()


async def test_reload_config_rebuilds_runtime_modules_without_resetting_paper_wallet(
    redis, tmp_path
):
    initial = tmp_path / "initial.yaml"
    updated = tmp_path / "updated.yaml"
    initial.write_text(
        "paper:\n  market_slippage_percent: 0.03\n"
        "risk:\n  account_risk_per_trade_percent: 1.0\n",
        encoding="utf-8",
    )
    updated.write_text(
        "paper:\n  market_slippage_percent: 0.2\n"
        "risk:\n  account_risk_per_trade_percent: 0.5\n",
        encoding="utf-8",
    )
    rt = _runtime_with_config(redis, initial)
    await rt.startup()
    assert rt._paper_engine is not None
    rt._paper_engine.balance = Decimal("9000")
    rt.secrets.quantbot_config = str(updated)

    await rt.handle_command(Command(type=CommandType.RELOAD_CONFIG))

    assert rt._risk_manager is not None
    assert rt._risk_manager.cfg.risk.account_risk_per_trade_percent == 0.5
    assert rt._trading is not None
    assert rt._trading.cfg.risk.account_risk_per_trade_percent == 0.5
    assert rt._paper_engine.slippage == Decimal("0.2")
    assert rt._paper_engine.balance == Decimal("9000")
    await rt.shutdown()


async def test_reload_config_uses_yaml_mode(redis, tmp_path):
    initial = tmp_path / "initial.yaml"
    updated = tmp_path / "updated.yaml"
    initial.write_text('bot:\n  mode: "PAPER"\n', encoding="utf-8")
    updated.write_text('bot:\n  mode: "LIVE"\n', encoding="utf-8")
    rt = _runtime_with_config(redis, initial)
    await rt.startup()
    rt.secrets.quantbot_config = str(updated)

    await rt.handle_command(Command(type=CommandType.RELOAD_CONFIG))

    assert rt.config.bot.mode == BotMode.LIVE
    assert rt._trading is not None
    assert rt._trading.mode == BotMode.LIVE
    await rt.shutdown()


async def test_start_ignored_when_not_standby(redis):
    rt = _runtime(redis)
    await rt.startup()
    await rt.handle_command(Command(type=CommandType.START_BOT))
    # second START while RUNNING must be ignored, not crash
    await rt.handle_command(Command(type=CommandType.START_BOT))
    assert rt.state_machine.state == BotState.RUNNING
    await rt.shutdown()
