"""BotRuntime lifecycle tests with injected fakeredis + FakeGateway."""

from decimal import Decimal

import fakeredis.aioredis
import pytest

from apps.bot.runtime import BotRuntime
from packages.config import load_app_config
from packages.config.settings import Secrets
from packages.core.enums import (
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
from packages.core.models import Order, Position
from packages.messaging import (
    Command,
    CommandQueue,
    CommandType,
    state_keys,
)
from tests.fakes import FakeGateway
from tests.fakes.builders import series_from_closes, symbol_meta, ticker


def _runtime(redis, gateway=None):
    cfg = load_app_config("config/quantbot.yaml")
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
    assert await redis.get(state_keys.BOT_MODE) == "PAPER"
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


async def test_scanner_refresh_populates_runtime_watchlist(redis):
    gw = FakeGateway()
    gw.set_instruments([symbol_meta(symbol="BTCUSDT", launch_time_ms=0)])
    gw.set_ticker(ticker(symbol="BTCUSDT", turnover_24h="100000000"))
    gw.set_kline(
        "BTCUSDT",
        "15",
        series_from_closes(["100"] * 80, symbol="BTCUSDT", interval="15"),
    )
    rt = _runtime(redis, gw)
    await rt.startup()
    await rt._collector.refresh_tickers()
    await rt._refresh_watchlist_if_due(force=True)
    assert rt._watch_symbols() == ["BTCUSDT"]
    await rt.shutdown()


async def test_close_position_command_closes_bot_position(redis):
    gw = FakeGateway()
    gw.set_ticker(ticker(symbol="BTCUSDT", bid="100", ask="100.1"))
    rt = _runtime(redis, gw)
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
    rt = _runtime(redis, gw)
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
    rt = _runtime(redis, gw)
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


async def test_start_ignored_when_not_standby(redis):
    rt = _runtime(redis)
    await rt.startup()
    await rt.handle_command(Command(type=CommandType.START_BOT))
    # second START while RUNNING must be ignored, not crash
    await rt.handle_command(Command(type=CommandType.START_BOT))
    assert rt.state_machine.state == BotState.RUNNING
    await rt.shutdown()
