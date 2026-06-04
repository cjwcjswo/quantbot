"""Tests for PositionManager lifecycle decisions (impl doc §14)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.core.enums import (
    EntryMode,
    ExitReason,
    PositionSide,
    PositionStatus,
)
from packages.core.models import Position
from packages.position import PositionAction, PositionActionType, PositionManager
from tests.fakes.builders import candle
from tests.fakes.builders import indicator_snapshot as snap


def _pos(
    *,
    entry="100",
    risk="1",
    side=PositionSide.LONG,
    mode=EntryMode.BREAKOUT_CONFIRM,
    bars=0,
):
    return Position(
        symbol="BTCUSDT",
        side=side,
        status=PositionStatus.ACTIVE,
        qty=Decimal("10"),
        avg_entry_price=Decimal(entry),
        initial_risk_per_unit=Decimal(risk),
        stop_loss_price=Decimal("99"),
        take_profit_price=Decimal("102"),
        entry_mode=mode,
        bars_since_entry=bars,
    )


def _types(actions: list[PositionAction]):
    return {a.type for a in actions}


def test_partial_take_profit_at_2r(config):
    pm = PositionManager(config)
    pos = _pos()
    actions = pm.evaluate(
        pos, price=Decimal("102"), atr=Decimal("1"),
        candle_1m=candle(h="102", l="100", c="102"),
    )
    assert PositionActionType.PARTIAL_TP in _types(actions)
    pa = next(a for a in actions if a.type == PositionActionType.PARTIAL_TP)
    assert pa.qty == Decimal("5")  # 50% of 10
    assert pos.partial_tp_done


def test_trailing_stop_exit(config):
    pm = PositionManager(config)
    pos = _pos()
    # bar 1: price hits +2R, sets highest=102, trailing active, stop ratchets to 100
    pm.evaluate(pos, price=Decimal("102"), atr=Decimal("1"),
                candle_1m=candle(h="102", l="101", c="102"))
    # bar 2: price falls to 99 <= trail stop (102 - 2*1 = 100) => trailing exit
    actions = pm.evaluate(pos, price=Decimal("99"), atr=Decimal("1"),
                          candle_1m=candle(h="102", l="99", c="99"))
    assert PositionActionType.EXIT in _types(actions)
    assert actions[0].reason == ExitReason.TRAILING_STOP


def test_max_holding_exit(config):
    pm = PositionManager(config)
    pos = _pos()
    pos.opened_at = datetime.now(timezone.utc) - timedelta(minutes=200)
    actions = pm.evaluate(pos, price=Decimal("100.1"), atr=Decimal("1"),
                          candle_1m=candle(h="100.2", l="100", c="100.1"))
    assert actions[0].type == PositionActionType.EXIT
    assert actions[0].reason == ExitReason.MAX_HOLDING_TIME


def test_stagnation_breakout_reduce_then_close(config):
    pm = PositionManager(config)
    pos = _pos(mode=EntryMode.BREAKOUT_CONFIRM, bars=4)
    # bar -> bars=5, max_r < 0.5 => REDUCE 50%
    actions = pm.evaluate(pos, price=Decimal("100"), atr=Decimal("1"),
                          candle_1m=candle(h="100.1", l="99.9", c="100"))
    assert actions[0].type == PositionActionType.REDUCE
    # advance to bars >= 10 without 1R => EXIT STAGNATION
    pos.bars_since_entry = 9
    actions = pm.evaluate(pos, price=Decimal("100"), atr=Decimal("1"),
                          candle_1m=candle(h="100.1", l="99.9", c="100"))
    assert actions[0].type == PositionActionType.EXIT
    assert actions[0].reason == ExitReason.STAGNATION


def test_scenario_invalid_reduce_then_exit(config):
    pm = PositionManager(config)
    pos = _pos(mode=EntryMode.RETEST_CONFIRM)
    invalid_5m = snap(timeframe="5", close="98", ema20="100", atr="1", valid=True)
    flat = candle(h="100.1", l="99.9", c="100")
    # invalidation => REDUCE 50% and open 3-bar recovery window
    a1 = pm.evaluate(pos, price=Decimal("100"), atr=Decimal("1"),
                     candle_1m=flat, snapshot_5m=invalid_5m)
    assert a1[0].type == PositionActionType.REDUCE
    assert a1[0].reason == ExitReason.SCENARIO_INVALID
    # 3 bars without +0.5R recovery => EXIT
    last = None
    for _ in range(3):
        last = pm.evaluate(pos, price=Decimal("100"), atr=Decimal("1"),
                           candle_1m=flat, snapshot_5m=invalid_5m)
    assert last[0].type == PositionActionType.EXIT
    assert last[0].reason == ExitReason.SCENARIO_INVALID


def test_scenario_invalid_after_two_closes_below_breakout_level(config):
    pm = PositionManager(config)
    pos = _pos(mode=EntryMode.BREAKOUT_CONFIRM)
    pos.breakout_level = Decimal("100")
    first = pm.evaluate(
        pos, price=Decimal("99.9"), atr=Decimal("1"),
        candle_1m=candle(c="99.9"),
    )
    assert first == []
    second = pm.evaluate(
        pos, price=Decimal("99.8"), atr=Decimal("1"),
        candle_1m=candle(c="99.8"),
    )
    assert second[0].type == PositionActionType.REDUCE
    assert second[0].reason == ExitReason.SCENARIO_INVALID


def test_external_position_not_managed(config):
    from packages.core.enums import PositionSource

    pm = PositionManager(config)
    pos = _pos()
    pos.source = PositionSource.EXTERNAL
    assert pm.evaluate(pos, price=Decimal("105"), atr=Decimal("1")) == []


def test_short_partial_take_profit(config):
    pm = PositionManager(config)
    pos = _pos(side=PositionSide.SHORT, entry="100", risk="1")
    # short +2R => price 98
    actions = pm.evaluate(pos, price=Decimal("98"), atr=Decimal("1"),
                          candle_1m=candle(h="100", l="98", c="98"))
    assert PositionActionType.PARTIAL_TP in _types(actions)
