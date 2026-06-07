"""Tests for RiskManager final approval (impl doc §13)."""

from decimal import Decimal

from packages.core.enums import EntryMode, PositionSide, PositionStatus, SignalDirection
from packages.entry.entry_timing_engine import EntryDecision
from packages.core.models import Position
from packages.risk import RiskContext, RiskManager
from tests.fakes.builders import symbol_meta


def _decision(
    stop_atr="1.0",
    mode=EntryMode.BREAKOUT_CONFIRM,
    frac="0.30",
    symbol="BTCUSDT",
    direction=SignalDirection.LONG,
    structure_stop_price=None,
    has_compression=None,
    score="7",
):
    return EntryDecision(
        symbol=symbol,
        direction=direction,
        entry_mode=mode,
        position_fraction=Decimal(frac),
        stop_atr=Decimal(stop_atr),
        score=Decimal(score),
        reason="test",
        structure_stop_price=(
            Decimal(str(structure_stop_price))
            if structure_stop_price is not None
            else None
        ),
        has_compression=has_compression,
    )


def _approve(
    config,
    decision=None,
    ctx=None,
    meta=None,
    atr="1",
    entry="100",
    use_target_notional=False,
):
    config.risk.target_notional_percent.enabled = use_target_notional
    rm = RiskManager(config)
    return rm.approve(
        decision or _decision(),
        entry_price=Decimal(entry),
        atr=Decimal(atr),
        symbol_meta=meta or symbol_meta(min_qty="0.001"),
        ctx=ctx or RiskContext(equity=Decimal("10000")),
    )


def test_happy_path_approved(config):
    d = _approve(config)
    assert d.approved
    assert d.side == PositionSide.LONG
    assert d.qty == Decimal("75.0")
    assert d.stop_loss_price == Decimal("99")
    assert d.take_profit_price == Decimal("102")
    assert d.leverage >= Decimal("1")


def test_position_fraction_reduces_sizing(config):
    full = _approve(config, decision=_decision(frac="0.30"))
    reduced = _approve(config, decision=_decision(frac="0.20"))

    assert full.approved
    assert reduced.approved
    assert full.qty == Decimal("75.0")
    assert reduced.qty == Decimal("50.0")


def test_tpsl_prices_are_rounded_to_tick(config):
    d = _approve(
        config,
        meta=symbol_meta(tick="0.0001", step="0.1", min_qty="0.1"),
        atr="0.0003473864836708189304168911",
        entry="0.1597",
    )

    assert d.approved
    assert d.stop_loss_price == Decimal("0.1593")
    assert d.take_profit_price == Decimal("0.1605")


def test_stop_too_tight(config):
    d = _approve(config, decision=_decision(stop_atr="0.3"))
    assert not d.approved and d.reason == "STOP_DISTANCE_TOO_NARROW"


def test_stop_too_wide(config):
    d = _approve(config, decision=_decision(stop_atr="2.0"))
    assert not d.approved and d.reason == "STOP_DISTANCE_TOO_WIDE"


def test_scout_min_stop_distance_percent_widens_low_atr_stop(config):
    d = _approve(
        config,
        decision=_decision(
            stop_atr="0.7",
            mode=EntryMode.PRE_BREAKOUT_SCOUT,
            frac="0.25",
        ),
        atr="0.2",
        entry="100",
    )

    assert d.approved
    assert d.stop_loss_price == Decimal("99.5")
    assert d.stop_metadata["atr_stop_price"] == "99.8"
    assert d.stop_metadata["min_distance_stop_price"] == "99.5"
    assert d.stop_metadata["min_distance_stop_applied"] is True
    assert d.stop_metadata["stop_distance_percent"] == "0.500"


def test_scout_short_min_stop_distance_rounds_away_from_entry(config):
    d = _approve(
        config,
        decision=_decision(
            stop_atr="0.7",
            mode=EntryMode.PRE_BREAKOUT_SCOUT,
            frac="0.25",
            direction=SignalDirection.SHORT,
        ),
        atr="0.2",
        entry="100",
    )

    assert d.approved
    assert d.stop_loss_price == Decimal("100.5")
    assert d.stop_metadata["atr_stop_price"] == "100.2"
    assert d.stop_metadata["min_distance_stop_price"] == "100.5"
    assert d.stop_metadata["stop_distance_percent"] == "0.500"


def test_tiny_tick_scout_min_stop_does_not_round_inside_min_distance(config):
    d = _approve(
        config,
        decision=_decision(
            stop_atr="1.3",
            mode=EntryMode.PRE_BREAKOUT_SCOUT,
            frac="0.25",
            symbol="1000PEPEUSDT",
        ),
        atr="0.000004032174882507967987170308",
        entry="0.002751",
        meta=symbol_meta(
            symbol="1000PEPEUSDT",
            tick="0.000001",
            step="100",
            min_qty="100",
        ),
    )

    assert d.approved
    assert d.stop_loss_price == Decimal("0.002738")
    assert d.stop_metadata["min_distance_stop_price"] == "0.002738"
    assert Decimal(d.stop_metadata["stop_distance_percent"]) >= Decimal("0.45")


def test_scout_structure_stop_can_widen_short_stop(config):
    d = _approve(
        config,
        decision=_decision(
            stop_atr="1.0",
            mode=EntryMode.PRE_BREAKOUT_SCOUT,
            frac="0.25",
            direction=SignalDirection.SHORT,
            structure_stop_price="101.8",
        ),
    )

    assert d.approved
    assert d.stop_loss_price == Decimal("101.8")
    assert d.stop_metadata["structure_stop_price"] == "101.8"
    assert d.stop_metadata["selected_stop_price"] == "101.8"


def test_retest_uses_retest_max_stop_distance_guard(config):
    d = _approve(
        config,
        decision=_decision(
            stop_atr="1.7",
            mode=EntryMode.RETEST_CONFIRM,
            frac="0.40",
        ),
    )
    assert d.approved
    assert d.stop_loss_price == Decimal("98.3")


def test_retest_rejects_above_retest_max_stop_distance(config):
    d = _approve(
        config,
        decision=_decision(
            stop_atr="1.9",
            mode=EntryMode.RETEST_CONFIRM,
            frac="0.40",
        ),
    )
    assert not d.approved
    assert d.reason == "STOP_DISTANCE_TOO_WIDE"
    assert d.stop_metadata["risk_reject_reason"] == "STOP_DISTANCE_TOO_WIDE"


def test_short_structure_stop_higher_than_atr_stop_is_selected(config):
    d = _approve(
        config,
        decision=_decision(
            stop_atr="1.3",
            mode=EntryMode.RETEST_CONFIRM,
            frac="0.40",
            direction=SignalDirection.SHORT,
            structure_stop_price="101.8",
        ),
    )
    assert d.approved
    assert d.stop_loss_price == Decimal("101.8")
    assert d.stop_metadata["atr_stop_price"] == "101.3"
    assert d.stop_metadata["structure_stop_price"] == "101.8"
    assert d.stop_metadata["selected_stop_price"] == "101.8"


def test_long_structure_stop_lower_than_atr_stop_is_selected(config):
    d = _approve(
        config,
        decision=_decision(
            stop_atr="1.3",
            mode=EntryMode.RETEST_CONFIRM,
            frac="0.40",
            structure_stop_price="98.2",
        ),
    )
    assert d.approved
    assert d.stop_loss_price == Decimal("98.2")
    assert d.stop_metadata["atr_stop_price"] == "98.7"
    assert d.stop_metadata["structure_stop_price"] == "98.2"
    assert d.stop_metadata["selected_stop_price"] == "98.2"


def test_retest_structure_unavailable_uses_atr_stop(config):
    d = _approve(
        config,
        decision=_decision(
            stop_atr="1.3",
            mode=EntryMode.RETEST_CONFIRM,
            frac="0.40",
        ),
    )
    assert d.approved
    assert d.stop_loss_price == Decimal("98.7")
    assert "structure_stop_price" not in d.stop_metadata


def test_wider_retest_stop_reduces_qty(config):
    tight = _approve(
        config,
        decision=_decision(
            stop_atr="1.0",
            mode=EntryMode.RETEST_CONFIRM,
            frac="0.40",
        ),
    )
    wide = _approve(
        config,
        decision=_decision(
            stop_atr="1.3",
            mode=EntryMode.RETEST_CONFIRM,
            frac="0.40",
        ),
    )

    assert tight.approved and wide.approved
    assert wide.qty < tight.qty


def test_daily_loss_blocks(config):
    ctx = RiskContext(equity=Decimal("10000"), daily_loss_percent=Decimal("5.0"))
    d = _approve(config, ctx=ctx)
    assert not d.approved and d.reason == "DAILY_LOSS_LIMIT"


def test_max_positions(config):
    opens = [
        Position(symbol=f"S{i}USDT", side=PositionSide.LONG, status=PositionStatus.ACTIVE,
                 qty=Decimal("1"), avg_entry_price=Decimal("10"))
        for i in range(config.bot.max_active_positions)
    ]
    ctx = RiskContext(equity=Decimal("10000"), open_positions=opens)
    d = _approve(config, ctx=ctx)
    assert not d.approved and d.reason == "MAX_POSITIONS"


def test_symbol_already_open(config):
    opens = [
        Position(symbol="BTCUSDT", side=PositionSide.LONG, status=PositionStatus.ACTIVE,
                 qty=Decimal("1"), avg_entry_price=Decimal("100"))
    ]
    ctx = RiskContext(equity=Decimal("10000"), open_positions=opens)
    d = _approve(config, ctx=ctx)
    assert not d.approved and d.reason == "SYMBOL_ALREADY_OPEN"


def test_below_min_qty(config):
    d = _approve(config, meta=symbol_meta(min_qty="100"))
    assert not d.approved and d.reason == "BELOW_MIN_QTY"


def test_symbol_risk_exceeded(config):
    config.risk.max_symbol_risk_percent = 0.1  # 0.75% computed > 0.1%
    d = _approve(config)
    assert not d.approved and d.reason == "SYMBOL_RISK_EXCEEDED"


def test_total_risk_exceeded(config):
    big = Position(
        symbol="ETHUSDT", side=PositionSide.LONG, status=PositionStatus.ACTIVE,
        qty=Decimal("1"), avg_entry_price=Decimal("100"),
        initial_risk_per_unit=Decimal("950"),  # 9.5% of 10000
    )
    ctx = RiskContext(equity=Decimal("10000"), open_positions=[big])
    d = _approve(config, ctx=ctx)
    assert not d.approved and d.reason == "TOTAL_RISK_EXCEEDED"


def test_target_notional_lifts_scout_no_compression(config):
    d = _approve(
        config,
        decision=_decision(
            stop_atr="3.0",
            mode=EntryMode.PRE_BREAKOUT_SCOUT,
            frac="0.30",
            has_compression=False,
        ),
        use_target_notional=True,
    )

    assert d.approved
    assert d.notional == Decimal("3000.0")
    assert d.qty == Decimal("30.0")
    assert d.risk_usdt == Decimal("90.0")
    assert Decimal(d.stop_metadata["target_notional_percent"]) == Decimal("30")
    assert d.stop_metadata["target_notional_applied"] is True


def test_target_notional_uses_compressed_scout_percent(config):
    d = _approve(
        config,
        decision=_decision(
            stop_atr="3.0",
            mode=EntryMode.PRE_BREAKOUT_SCOUT,
            frac="0.60",
            has_compression=True,
        ),
        use_target_notional=True,
    )

    assert d.approved
    assert d.notional == Decimal("5000.0")
    assert d.qty == Decimal("50.0")
    assert Decimal(d.stop_metadata["target_notional_percent"]) == Decimal("50")


def test_target_notional_can_require_leverage(config):
    config.risk.target_notional_percent.retest_confirm = 150
    d = _approve(
        config,
        decision=_decision(
            stop_atr="1.8",
            mode=EntryMode.RETEST_CONFIRM,
            frac="0.85",
        ),
        use_target_notional=True,
    )

    assert d.approved
    assert d.notional == Decimal("15000.0")
    assert d.leverage == Decimal("2")
    assert d.stop_metadata["target_notional_applied"] is True


def test_high_quality_target_notional_overrides_mode_target(config):
    d = _approve(
        config,
        decision=_decision(
            stop_atr="2.0",
            mode=EntryMode.PRE_BREAKOUT_SCOUT,
            frac="0.30",
            has_compression=False,
            score="9",
        ),
        use_target_notional=True,
    )

    assert d.approved
    assert d.notional == Decimal("12000.0")
    assert d.leverage == Decimal("2")
    assert d.risk_usdt == Decimal("240.0")
    assert d.stop_metadata["high_quality"] is True
    assert Decimal(d.stop_metadata["target_notional_percent"]) == Decimal("120")


def test_target_notional_still_respects_symbol_risk_limit(config):
    config.risk.target_notional_percent.retest_confirm = 200
    d = _approve(
        config,
        decision=_decision(
            stop_atr="1.8",
            mode=EntryMode.RETEST_CONFIRM,
            frac="0.85",
        ),
        use_target_notional=True,
    )

    assert not d.approved
    assert d.reason == "SYMBOL_RISK_EXCEEDED"


def test_liquidation_distance_guard(config):
    # Force the percent guard to trip by demanding an impossibly far liq.
    config.liquidation_guard.min_liquidation_distance_percent = 99.9
    d = _approve(config)
    assert not d.approved and d.reason == "LIQ_TOO_CLOSE_PCT"
