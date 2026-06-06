"""Runner Mode execution-side tests."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from apps.bot.runtime.runtime_state import RuntimeState
from apps.bot.workers.trading_pipeline import TradingService
from packages.core.enums import BotMode, PositionSide, PositionStatus
from packages.core.events import BotEventType
from packages.core.models import Position
from packages.messaging import EventBus
from packages.position import PositionAction, PositionActionType
from tests.fakes.builders import candle


class _FailingProtection:
    async def sync_stop_loss(self, _position):
        raise RuntimeError("boom")


def _service(config, events, *, protection=None):
    return TradingService(
        config,
        mode=BotMode.LIVE,
        signal_engine=None,
        entry_engine=None,
        risk_manager=None,
        position_manager=None,
        state=RuntimeState(),
        executor=None,
        protection_manager=protection,
        event_bus=EventBus(redis=None, sink=events),
    )


def _runner_position():
    return Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.ACTIVE,
        qty=Decimal("5"),
        avg_entry_price=Decimal("100"),
        initial_risk_per_unit=Decimal("1"),
        stop_loss_price=Decimal("101"),
        runner_mode_active=True,
        runner_trend_strength="STRONG",
        runner_trailing_atr_multiplier=Decimal("2.8"),
    )


async def test_runner_exchange_sl_failure_does_not_close_position(config, events):
    service = _service(config, events, protection=_FailingProtection())
    pos = _runner_position()
    action = PositionAction(
        type=PositionActionType.TRAIL_UPDATE,
        new_stop=Decimal("101"),
        data={"new_trailing_stop": "101"},
    )

    await service._sync_trailing_stop(pos, action)

    assert pos.status == PositionStatus.ACTIVE
    assert pos.runner_exchange_sl_update_failures == 1
    failed = events.of_type(BotEventType.RUNNER_EXCHANGE_SL_UPDATE_FAILED)
    assert len(failed) == 1
    assert failed[0].data["consecutive_failures"] == 1


async def test_runner_post_exit_mfe_logged(config, events):
    service = _service(config, events)
    pos = _runner_position()
    pos.status = PositionStatus.CLOSED
    pos.closed_at = datetime.now(timezone.utc) - timedelta(minutes=5)

    service.start_post_exit_mfe(pos, exit_price=Decimal("102"))
    await service.update_post_exit_mfe(
        "BTCUSDT",
        price=Decimal("104"),
        candle_1m=candle(h="106", l="103", c="104"),
        now=pos.closed_at + timedelta(minutes=5, seconds=1),
    )

    mfe = events.of_type(BotEventType.RUNNER_POST_EXIT_MFE)
    assert len(mfe) == 1
    assert mfe[0].data["window_min"] == 5
    assert mfe[0].data["post_exit_mfe"] == "4"
    assert mfe[0].data["post_exit_mfe_r"] == "4"
