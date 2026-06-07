"""Tests for PositionManager lifecycle decisions (impl doc §14)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.core.enums import (
    EntryMode,
    ExitReason,
    PositionSide,
    PositionStatus,
    ScoutState,
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


def _scout_pos(*, side=PositionSide.SHORT, bars=0):
    box_high = Decimal("102")
    box_low = Decimal("100")
    return Position(
        symbol="BTCUSDT",
        side=side,
        status=PositionStatus.ACTIVE,
        qty=Decimal("10"),
        avg_entry_price=Decimal("100"),
        initial_risk_per_unit=Decimal("1"),
        stop_loss_price=Decimal("101") if side == PositionSide.SHORT else Decimal("99"),
        take_profit_price=Decimal("98") if side == PositionSide.SHORT else Decimal("102"),
        entry_mode=EntryMode.PRE_BREAKOUT_SCOUT,
        bars_since_entry=bars,
        scout_state=ScoutState.SCOUT_PENDING,
        scout_entry_box_high=box_high,
        scout_entry_box_low=box_low,
        scout_entry_box_mid=(box_high + box_low) / Decimal("2"),
        scout_entry_level=box_low if side == PositionSide.SHORT else box_high,
        scout_entry_bar_index=0,
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
    assert actions[0].event_type == "STAGNATION_REDUCE"
    assert actions[0].data["reason"] == "STAGNATION"
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
    assert a1[0].event_type == "SCENARIO_INVALID_REDUCE"
    assert a1[0].data["reason"] == "SCENARIO_INVALID"
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
    assert second[0].event_type == "SCENARIO_INVALID_REDUCE"


def test_scout_pending_grace_skips_general_scenario_invalid(config):
    pm = PositionManager(config)
    pos = _scout_pos(side=PositionSide.SHORT, bars=0)
    invalid_5m = snap(timeframe="5", close="102", ema20="100", atr="1", valid=True)

    actions = pm.evaluate(
        pos,
        price=Decimal("100.5"),
        atr=Decimal("1"),
        candle_1m=candle(o="100.4", h="100.7", l="100.3", c="100.5"),
        snapshot_5m=invalid_5m,
    )

    assert actions == []
    assert pos.scout_state == ScoutState.SCOUT_PENDING
    assert pos.scout_defensive_reduction_count == 0


def test_short_scout_confirm_activates_active_trend(config):
    pm = PositionManager(config)
    pos = _scout_pos(side=PositionSide.SHORT, bars=2)

    actions = pm.evaluate(
        pos,
        price=Decimal("97.9"),
        atr=Decimal("1"),
        candle_1m=candle(o="99", h="99.2", l="97.8", c="97.9"),
        volume_ratio=Decimal("1.2"),
    )

    assert pos.scout_state == ScoutState.ACTIVE_TREND
    assert [a.event_type for a in actions if a.event_type] == [
        "SCOUT_CONFIRMED",
        "SCOUT_ACTIVATED",
    ]


def test_long_scout_confirm_activates_active_trend(config):
    pm = PositionManager(config)
    pos = _scout_pos(side=PositionSide.LONG, bars=2)

    actions = pm.evaluate(
        pos,
        price=Decimal("102.2"),
        atr=Decimal("1"),
        candle_1m=candle(o="101", h="102.3", l="100.9", c="102.2"),
        volume_ratio=Decimal("1.2"),
    )

    assert pos.scout_state == ScoutState.ACTIVE_TREND
    assert [a.event_type for a in actions if a.event_type] == [
        "SCOUT_CONFIRMED",
        "SCOUT_ACTIVATED",
    ]


def test_scout_pending_defensive_reduce_only_once(config):
    pm = PositionManager(config)
    pos = _scout_pos(side=PositionSide.SHORT, bars=5)
    weak = candle(o="100.8", h="101.3", l="100.7", c="101.2")

    first = pm.evaluate(pos, price=Decimal("101.2"), atr=Decimal("1"), candle_1m=weak)
    second = pm.evaluate(pos, price=Decimal("101.2"), atr=Decimal("1"), candle_1m=weak)

    assert first[0].type == PositionActionType.REDUCE
    assert first[0].qty == Decimal("5.0")
    assert first[0].reason == ExitReason.SCOUT_DEFENSIVE_REDUCE
    assert first[0].event_type == "SCOUT_DEFENSIVE_REDUCE"
    assert pos.scout_defensive_reduction_count == 1
    assert all(a.type != PositionActionType.REDUCE for a in second)


def test_home_like_long_scout_strong_candle_starts_warning_without_reduce(config):
    pm = PositionManager(config)
    pos = _scout_pos(side=PositionSide.LONG, bars=0)

    actions = pm.evaluate(
        pos,
        price=Decimal("99.117"),
        atr=Decimal("1"),
        candle_1m=candle(o="99.9039", h="100", l="99", c="99.117"),
        volume_ratio=Decimal("2.02"),
    )

    assert [a.type for a in actions] == [PositionActionType.SCOUT_EVENT]
    assert actions[0].event_type == "SCOUT_WARNING_STARTED"
    assert actions[0].data["reason"] == "STRONG_BEARISH_CANDLE"
    assert actions[0].data["opposite_move_atr"] == "0.7869"
    assert pos.scout_state == ScoutState.SCOUT_WARNING
    assert pos.scout_warning_started_at_bar == 1
    assert pos.scout_defensive_reduction_count == 0


def test_scout_warning_recovers_without_reduce(config):
    pm = PositionManager(config)
    pos = _scout_pos(side=PositionSide.LONG, bars=1)
    pos.scout_state = ScoutState.SCOUT_WARNING
    pos.scout_warning_started_at_bar = 1
    pos.scout_warning_reason = "STRONG_BEARISH_CANDLE"

    actions = pm.evaluate(
        pos,
        price=Decimal("100.2"),
        atr=Decimal("1"),
        candle_1m=candle(o="99.8", h="100.4", l="99.7", c="100.2"),
    )

    assert [a.type for a in actions] == [PositionActionType.SCOUT_EVENT]
    assert actions[0].event_type == "SCOUT_WARNING_RECOVERED"
    assert pos.scout_state == ScoutState.SCOUT_PENDING
    assert pos.scout_warning_started_at_bar is None
    assert pos.scout_defensive_reduction_count == 0


def test_scout_warning_failed_after_confirm_bars_reduces_once(config):
    pm = PositionManager(config)
    pos = _scout_pos(side=PositionSide.LONG, bars=2)
    pos.scout_state = ScoutState.SCOUT_WARNING
    pos.scout_warning_started_at_bar = 1
    pos.scout_warning_reason = "STRONG_BEARISH_CANDLE"

    actions = pm.evaluate(
        pos,
        price=Decimal("99.1"),
        atr=Decimal("1"),
        candle_1m=candle(o="99.6", h="99.8", l="99.0", c="99.1"),
    )

    assert [a.type for a in actions] == [PositionActionType.REDUCE]
    assert actions[0].qty == Decimal("5.0")
    assert actions[0].event_type == "SCOUT_DEFENSIVE_REDUCE"
    assert actions[0].reason == ExitReason.SCOUT_DEFENSIVE_REDUCE
    assert actions[0].data["warning_bars"] == 2
    assert pos.scout_state == ScoutState.SCOUT_PENDING
    assert pos.scout_warning_started_at_bar is None
    assert pos.scout_defensive_reduction_count == 1

    second = pm.evaluate(
        pos,
        price=Decimal("99.1"),
        atr=Decimal("1"),
        candle_1m=candle(o="99.6", h="99.8", l="99.0", c="99.1"),
        volume_ratio=Decimal("2"),
    )
    assert all(a.type != PositionActionType.REDUCE for a in second)


def test_scout_catastrophic_candle_reduces_immediately(config):
    pm = PositionManager(config)
    pos = _scout_pos(side=PositionSide.LONG, bars=0)

    actions = pm.evaluate(
        pos,
        price=Decimal("99.1"),
        atr=Decimal("1"),
        candle_1m=candle(o="100.6", h="101", l="99", c="99.1"),
        volume_ratio=Decimal("3.1"),
    )

    assert [a.type for a in actions] == [PositionActionType.REDUCE]
    assert actions[0].qty == Decimal("5.0")
    assert actions[0].event_type == "SCOUT_CATASTROPHIC_REDUCE"
    assert actions[0].reason == ExitReason.SCOUT_CATASTROPHIC_REDUCE
    assert actions[0].data["reason"] == "CATASTROPHIC_BEARISH_CANDLE"
    assert actions[0].data["opposite_move_atr"] == "1.5"
    assert pos.scout_defensive_reduction_count == 1


def test_scout_defensive_reduce_does_not_stack_with_stagnation(config):
    pm = PositionManager(config)
    pos = _scout_pos(side=PositionSide.SHORT, bars=7)

    actions = pm.evaluate(
        pos,
        price=Decimal("101.2"),
        atr=Decimal("1"),
        candle_1m=candle(o="100.8", h="101.3", l="100.7", c="101.2"),
    )

    assert [a.type for a in actions] == [PositionActionType.REDUCE]


def test_scout_stagnation_counts_unique_1m_candles_not_evaluations(config):
    pm = PositionManager(config)
    pos = _scout_pos(side=PositionSide.LONG, bars=0)
    pos.avg_entry_price = Decimal("101.8")
    pos.stop_loss_price = Decimal("101")
    pos.take_profit_price = Decimal("103.4")

    same_bar = candle(
        open_time_ms=60_000,
        o="101.5",
        h="101.7",
        l="101.4",
        c="101.6",
    )
    for _ in range(8):
        actions = pm.evaluate(
            pos,
            price=Decimal("101.6"),
            atr=Decimal("1"),
            candle_1m=same_bar,
            volume_ratio=Decimal("0.5"),
        )
        assert all(a.reason != ExitReason.STAGNATION for a in actions)

    assert pos.bars_since_entry == 1

    last_actions = []
    for i in range(2, 9):
        last_actions = pm.evaluate(
            pos,
            price=Decimal("101.6"),
            atr=Decimal("1"),
            candle_1m=candle(
                open_time_ms=i * 60_000,
                o="101.5",
                h="101.7",
                l="101.4",
                c="101.6",
            ),
            volume_ratio=Decimal("0.5"),
        )

    assert pos.bars_since_entry == 8
    assert last_actions[-1].type == PositionActionType.EXIT
    assert last_actions[-1].reason == ExitReason.STAGNATION


def test_active_trend_scout_uses_general_scenario_invalid(config):
    pm = PositionManager(config)
    pos = _scout_pos(side=PositionSide.SHORT, bars=3)
    pos.scout_state = ScoutState.ACTIVE_TREND
    invalid_5m = snap(timeframe="5", close="102", ema20="100", atr="1", valid=True)

    actions = pm.evaluate(
        pos,
        price=Decimal("100.5"),
        atr=Decimal("1"),
        candle_1m=candle(o="100.4", h="100.7", l="100.3", c="100.5"),
        snapshot_5m=invalid_5m,
    )

    assert actions[0].type == PositionActionType.REDUCE
    assert actions[0].reason == ExitReason.SCENARIO_INVALID
    assert actions[0].event_type == "SCENARIO_INVALID_REDUCE"


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


def test_runner_mode_activates_after_partial_tp(config):
    pm = PositionManager(config)
    pos = _pos()
    pos.partial_tp_done = True
    pos.qty = Decimal("5")
    actions = pm.activate_runner_after_partial_tp(
        pos,
        price=Decimal("102"),
        atr=Decimal("1"),
        candle_1m=candle(h="103", l="101", c="102"),
        snapshot_1m=snap(timeframe="1", close="102", ema20="101", rsi="55"),
        snapshot_5m=snap(timeframe="5", close="102", ema20="101"),
    )

    assert pos.runner_mode_active
    assert pos.runner_trend_strength == "STRONG"
    assert pos.runner_trailing_atr_multiplier == Decimal("2.8")
    assert pos.stop_loss_price == Decimal("100.2")
    assert [a.event_type for a in actions if a.event_type] == [
        "RUNNER_MODE_ACTIVATED",
        "RUNNER_TRAILING_UPDATED",
    ]


def test_short_runner_strong_trend_uses_2_8_atr(config):
    pm = PositionManager(config)
    pos = _pos(side=PositionSide.SHORT, entry="100", risk="1")
    pos.stop_loss_price = Decimal("101")
    pos.partial_tp_done = True
    pos.qty = Decimal("5")

    pm.activate_runner_after_partial_tp(
        pos,
        price=Decimal("98"),
        atr=Decimal("1"),
        candle_1m=candle(h="99", l="97.5", c="98"),
        snapshot_1m=snap(timeframe="1", close="98", ema20="99", rsi="40"),
        snapshot_5m=snap(timeframe="5", close="98", ema20="99"),
    )

    assert pos.runner_trend_strength == "STRONG"
    assert pos.runner_trailing_atr_multiplier == Decimal("2.8")
    assert pos.stop_loss_price == Decimal("100.3")


def test_runner_very_strong_uses_3_2_atr(config):
    pm = PositionManager(config)
    pos = _pos()
    pos.partial_tp_done = True
    pos.qty = Decimal("5")

    pm.activate_runner_after_partial_tp(
        pos,
        price=Decimal("105"),
        atr=Decimal("1"),
        candle_1m=candle(h="106", l="104", c="105"),
        snapshot_1m=snap(timeframe="1", close="105", ema20="103", rsi="56"),
        snapshot_5m=snap(timeframe="5", close="105", ema20="103"),
    )

    assert pos.runner_trend_strength == "VERY_STRONG"
    assert pos.runner_trailing_atr_multiplier == Decimal("3.2")
    assert pos.stop_loss_price == Decimal("102.8")


def test_runner_weak_trend_uses_2_0_atr(config):
    pm = PositionManager(config)
    pos = _pos()
    pos.partial_tp_done = True
    pos.qty = Decimal("5")

    pm.activate_runner_after_partial_tp(
        pos,
        price=Decimal("102"),
        atr=Decimal("1"),
        candle_1m=candle(h="103", l="101", c="102"),
        snapshot_1m=snap(timeframe="1", close="102", ema20="102.5", rsi="49"),
        snapshot_5m=snap(timeframe="5", close="102", ema20="101"),
    )

    assert pos.runner_trend_strength == "WEAK"
    assert pos.runner_trailing_atr_multiplier == Decimal("2.0")
    assert pos.stop_loss_price == Decimal("101")


def test_runner_strong_to_weak_requires_unique_bar_confirmation(config):
    pm = PositionManager(config)
    pos = _pos()
    pos.runner_mode_active = True
    pos.partial_tp_done = True
    pos.runner_trend_strength = "STRONG"
    pos.runner_trailing_atr_multiplier = Decimal("2.8")
    pos.highest_price = Decimal("104")

    first_bar = candle(open_time_ms=60_000, h="104", l="101.8", c="102")
    weak_rsi = snap(timeframe="1", close="102", ema20="101", rsi="49")
    hold_5m = snap(timeframe="5", close="102", ema20="101")

    pm.evaluate(
        pos,
        price=Decimal("102.3"),
        atr=Decimal("1"),
        candle_1m=first_bar,
        snapshot_1m=weak_rsi,
        snapshot_5m=hold_5m,
    )
    assert pos.runner_trend_strength == "STRONG"
    assert pos.runner_trailing_atr_multiplier == Decimal("2.8")

    pm.evaluate(
        pos,
        price=Decimal("102.3"),
        atr=Decimal("1"),
        candle_1m=first_bar,
        snapshot_1m=weak_rsi,
        snapshot_5m=hold_5m,
    )
    assert pos.runner_trend_strength == "STRONG"

    pm.evaluate(
        pos,
        price=Decimal("102.3"),
        atr=Decimal("1"),
        candle_1m=candle(open_time_ms=120_000, h="104", l="101.8", c="102"),
        snapshot_1m=weak_rsi,
        snapshot_5m=hold_5m,
    )
    assert pos.runner_trend_strength == "WEAK"
    assert pos.runner_trailing_atr_multiplier == Decimal("2.0")


def test_runner_long_stop_never_moves_against_position(config):
    pm = PositionManager(config)
    pos = _pos()
    pos.runner_mode_active = True
    pos.partial_tp_done = True
    pos.runner_trend_strength = "STRONG"
    pos.runner_trailing_atr_multiplier = Decimal("2.8")
    pos.highest_price = Decimal("103")
    pos.stop_loss_price = Decimal("101")

    actions = pm.evaluate(
        pos,
        price=Decimal("102"),
        atr=Decimal("1"),
        candle_1m=candle(h="102.5", l="101.5", c="102"),
        snapshot_1m=snap(timeframe="1", close="102", ema20="101", rsi="55"),
        snapshot_5m=snap(timeframe="5", close="102", ema20="101"),
    )

    assert PositionActionType.TRAIL_UPDATE not in _types(actions)
    assert pos.stop_loss_price == Decimal("101")


def test_runner_trailing_breach_uses_existing_tighter_stop(config):
    pm = PositionManager(config)
    pos = _pos()
    pos.runner_mode_active = True
    pos.partial_tp_done = True
    pos.runner_trend_strength = "VERY_STRONG"
    pos.runner_trailing_atr_multiplier = Decimal("3.2")
    pos.highest_price = Decimal("106")
    pos.stop_loss_price = Decimal("103")

    actions = pm.evaluate(
        pos,
        price=Decimal("102.9"),
        atr=Decimal("1"),
        candle_1m=candle(h="105", l="102.9", c="102.9"),
        snapshot_1m=snap(timeframe="1", close="102.9", ema20="101", rsi="56"),
        snapshot_5m=snap(timeframe="5", close="102.9", ema20="101"),
    )

    assert actions[-1].type == PositionActionType.EXIT
    assert actions[-1].reason == ExitReason.RUNNER_TRAILING_STOP


def test_runner_short_stop_never_moves_against_position(config):
    pm = PositionManager(config)
    pos = _pos(side=PositionSide.SHORT, entry="100", risk="1")
    pos.runner_mode_active = True
    pos.partial_tp_done = True
    pos.runner_trend_strength = "STRONG"
    pos.runner_trailing_atr_multiplier = Decimal("2.8")
    pos.lowest_price = Decimal("97")
    pos.stop_loss_price = Decimal("99")

    actions = pm.evaluate(
        pos,
        price=Decimal("98"),
        atr=Decimal("1"),
        candle_1m=candle(h="98.5", l="97.5", c="98"),
        snapshot_1m=snap(timeframe="1", close="98", ema20="99", rsi="40"),
        snapshot_5m=snap(timeframe="5", close="98", ema20="99"),
    )

    assert PositionActionType.TRAIL_UPDATE not in _types(actions)
    assert pos.stop_loss_price == Decimal("99")


def test_runner_disables_stagnation_exit(config):
    pm = PositionManager(config)
    pos = _pos(mode=EntryMode.BREAKOUT_CONFIRM, bars=12)
    pos.runner_mode_active = True
    pos.partial_tp_done = True
    pos.runner_trend_strength = "WEAK"
    pos.runner_trailing_atr_multiplier = Decimal("2.0")

    actions = pm.evaluate(
        pos,
        price=Decimal("100.1"),
        atr=Decimal("1"),
        candle_1m=candle(h="100.2", l="100", c="100.1"),
    )

    assert all(a.reason != ExitReason.STAGNATION for a in actions)
