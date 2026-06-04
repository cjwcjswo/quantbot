"""Tests for manual-intervention TP/SL resync + risk-exceeded wiring (impl doc §4.4)."""

from decimal import Decimal

from apps.bot.runtime.runtime_state import RuntimeState
from packages.core.enums import EntryMode, PositionSide, PositionSource, PositionStatus
from packages.core.events import BotEventType
from packages.core.models import ExchangePosition, Position
from packages.messaging import EventBus
from packages.reconciliation import ManualInterventionHandler


def _bot_position():
    return Position(
        symbol="BTCUSDT", side=PositionSide.LONG, status=PositionStatus.ACTIVE,
        source=PositionSource.BOT, qty=Decimal("1"), avg_entry_price=Decimal("100"),
        initial_risk_per_unit=Decimal("1"), entry_mode=EntryMode.BREAKOUT_CONFIRM,
    )


async def test_resync_failure_emits_emergency_tpsl_failed(config, events):
    state = RuntimeState()
    pos = _bot_position()
    state.positions["BTCUSDT"] = pos
    bus = EventBus(redis=None, sink=events)

    async def failing_resync(_position):
        return False  # §4.4 step 10

    handler = ManualInterventionHandler(
        state, bus, config.manual_intervention, protection_resync=failing_resync
    )
    await handler.handle_qty_mismatch(
        pos, ExchangePosition(symbol="BTCUSDT", side=PositionSide.LONG,
                              size=Decimal("2"), avg_price=Decimal("101")),
    )
    assert BotEventType.MANUAL_ADD_DETECTED in events.types()
    assert BotEventType.EMERGENCY_TPSL_FAILED in events.types()


async def test_risk_exceeded_event(config, events):
    state = RuntimeState()
    pos = _bot_position()
    state.positions["BTCUSDT"] = pos
    bus = EventBus(redis=None, sink=events)

    async def ok_resync(_position):
        return True

    handler = ManualInterventionHandler(
        state, bus, config.manual_intervention,
        protection_resync=ok_resync,
        risk_exceeded_check=lambda p: True,
    )
    await handler.handle_qty_mismatch(
        pos, ExchangePosition(symbol="BTCUSDT", side=PositionSide.LONG,
                              size=Decimal("5"), avg_price=Decimal("101")),
    )
    assert BotEventType.RISK_LIMIT_EXCEEDED_BY_MANUAL_INTERVENTION in events.types()
    assert BotEventType.EMERGENCY_TPSL_FAILED not in events.types()  # resync ok
