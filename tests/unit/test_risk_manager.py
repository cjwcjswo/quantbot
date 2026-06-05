"""Tests for RiskManager final approval (impl doc §13)."""

from decimal import Decimal

from packages.core.enums import EntryMode, PositionSide, PositionStatus, SignalDirection
from packages.entry.entry_timing_engine import EntryDecision
from packages.core.models import Position
from packages.risk import RiskContext, RiskManager
from tests.fakes.builders import symbol_meta


def _decision(stop_atr="1.0", mode=EntryMode.BREAKOUT_CONFIRM, frac="0.30", symbol="BTCUSDT"):
    return EntryDecision(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_mode=mode,
        position_fraction=Decimal(frac),
        stop_atr=Decimal(stop_atr),
        score=Decimal("7"),
        reason="test",
    )


def _approve(config, decision=None, ctx=None, meta=None, atr="1", entry="100"):
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
    assert d.qty == Decimal("30")
    assert d.stop_loss_price == Decimal("99")
    assert d.take_profit_price == Decimal("102")
    assert d.leverage >= Decimal("1")


def test_position_fraction_reduces_sizing(config):
    full = _approve(config, decision=_decision(frac="0.30"))
    reduced = _approve(config, decision=_decision(frac="0.20"))

    assert full.approved
    assert reduced.approved
    assert full.qty == Decimal("30")
    assert reduced.qty == Decimal("20")


def test_tpsl_prices_are_rounded_to_tick(config):
    d = _approve(
        config,
        meta=symbol_meta(tick="0.0001", step="0.1", min_qty="0.1"),
        atr="0.0003473864836708189304168911",
        entry="0.1597",
    )

    assert d.approved
    assert d.stop_loss_price == Decimal("0.1594")
    assert d.take_profit_price == Decimal("0.1603")


def test_stop_too_tight(config):
    d = _approve(config, decision=_decision(stop_atr="0.3"))
    assert not d.approved and d.reason == "STOP_TOO_TIGHT"


def test_stop_too_wide(config):
    d = _approve(config, decision=_decision(stop_atr="2.0"))
    assert not d.approved and d.reason == "STOP_TOO_WIDE"


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
    config.risk.max_symbol_risk_percent = 0.1  # 0.3% computed > 0.1%
    d = _approve(config)
    assert not d.approved and d.reason == "SYMBOL_RISK_EXCEEDED"


def test_total_risk_exceeded(config):
    big = Position(
        symbol="ETHUSDT", side=PositionSide.LONG, status=PositionStatus.ACTIVE,
        qty=Decimal("1"), avg_entry_price=Decimal("100"),
        initial_risk_per_unit=Decimal("480"),  # 4.8% of 10000
    )
    ctx = RiskContext(equity=Decimal("10000"), open_positions=[big])
    d = _approve(config, ctx=ctx)
    assert not d.approved and d.reason == "TOTAL_RISK_EXCEEDED"


def test_liquidation_distance_guard(config):
    # Force the percent guard to trip by demanding an impossibly far liq.
    config.liquidation_guard.min_liquidation_distance_percent = 99.9
    d = _approve(config)
    assert not d.approved and d.reason == "LIQ_TOO_CLOSE_PCT"
