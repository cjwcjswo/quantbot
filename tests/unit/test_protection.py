"""Tests for PositionProtectionManager (impl doc §5)."""

from decimal import Decimal

from packages.core.enums import PositionSide, PositionStatus
from packages.core.models import Position
from packages.execution import OrderManager
from packages.messaging import EventBus
from packages.position import PositionProtectionManager
from packages.core.events import BotEventType
from tests.fakes import FakeGateway


async def _noop_sleep(_):
    return None


def _position(symbol="BTCUSDT"):
    return Position(
        symbol=symbol,
        side=PositionSide.LONG,
        status=PositionStatus.PENDING,
        qty=Decimal("1"),
        avg_entry_price=Decimal("100"),
        stop_loss_price=Decimal("99"),
        take_profit_price=Decimal("102"),
    )


def _ppm(config, gw, events):
    bus = EventBus(redis=None, sink=events)
    om = OrderManager(gw, config)
    return PositionProtectionManager(gw, om, bus, config, sleep=_noop_sleep)


async def test_protect_success_makes_active(config, events):
    gw = FakeGateway()
    ppm = _ppm(config, gw, events)
    pos = _position()
    result = await ppm.protect(pos)
    assert result.protected
    assert pos.status == PositionStatus.ACTIVE
    assert BotEventType.TPSL_SET in events.types()
    assert BotEventType.TPSL_VERIFIED in events.types()


async def test_protect_verify_fail_emergency_close_order_locked(config, events):
    gw = FakeGateway()
    gw.disable_tpsl = True  # TP/SL never registers => verify fails
    gw.fill_ratio = Decimal("1")  # emergency close fills
    ppm = _ppm(config, gw, events)
    pos = _position()
    result = await ppm.protect(pos)
    assert not result.protected
    assert result.reason == "ORDER_LOCKED"
    assert result.closed
    assert pos.status == PositionStatus.CLOSED
    assert BotEventType.EMERGENCY_TPSL_FAILED in events.types()
    assert BotEventType.EMERGENCY_CLOSE in events.types()
    # the emergency exit was reduce-only
    assert gw.placed_orders[-1].reduce_only is True


async def test_protect_emergency_close_fail_emergency_stop(config, events):
    gw = FakeGateway()
    gw.disable_tpsl = True
    gw.fill_ratio = Decimal("0")  # emergency close does NOT fill
    ppm = _ppm(config, gw, events)
    pos = _position()
    result = await ppm.protect(pos)
    assert not result.protected
    assert result.reason == "EMERGENCY_STOP"
    assert not result.closed
