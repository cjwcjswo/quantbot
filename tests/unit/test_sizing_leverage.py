"""Tests for position sizing, leverage policy and price levels (impl doc §13, §5.4)."""

from decimal import Decimal

import pytest

from packages.core.enums import EntryMode, PositionSide
from packages.core.errors import RiskRejection
from packages.risk import (
    choose_leverage,
    compute_size,
    estimate_liq_price,
    max_leverage,
    stop_loss_price,
    take_profit_price,
)


def test_compute_size_basic():
    r = compute_size(
        equity=Decimal("10000"),
        account_risk_per_trade_percent=Decimal("1.0"),
        position_fraction=Decimal("0.30"),
        entry_price=Decimal("100"),
        stop_loss_price=Decimal("99"),
        qty_step=Decimal("0.001"),
    )
    # mode_risk = 10000*1%*0.30 = 30; stop_dist% = 0.01; notional = 3000; qty = 30
    assert r.notional == Decimal("3000")
    assert r.qty == Decimal("30")
    assert r.risk_usdt == Decimal("30")


def test_compute_size_leverage_cap():
    r = compute_size(
        equity=Decimal("10000"),
        account_risk_per_trade_percent=Decimal("1.0"),
        position_fraction=Decimal("0.30"),
        entry_price=Decimal("100"),
        stop_loss_price=Decimal("99"),
        qty_step=Decimal("0.001"),
        max_notional=Decimal("2000"),
    )
    assert r.notional == Decimal("2000")
    assert r.qty == Decimal("20")


def test_compute_size_target_notional_lifts_risk_size():
    r = compute_size(
        equity=Decimal("10000"),
        account_risk_per_trade_percent=Decimal("1.0"),
        position_fraction=Decimal("0.30"),
        entry_price=Decimal("100"),
        stop_loss_price=Decimal("97"),
        qty_step=Decimal("0.001"),
        target_notional=Decimal("1500"),
    )
    assert r.notional == Decimal("1500")
    assert r.qty == Decimal("15")
    assert r.risk_usdt == Decimal("45")


def test_compute_size_leverage_cap_bounds_target_notional():
    r = compute_size(
        equity=Decimal("10000"),
        account_risk_per_trade_percent=Decimal("1.0"),
        position_fraction=Decimal("0.30"),
        entry_price=Decimal("100"),
        stop_loss_price=Decimal("97"),
        qty_step=Decimal("0.001"),
        target_notional=Decimal("5000"),
        max_notional=Decimal("2000"),
    )
    assert r.notional == Decimal("2000")
    assert r.qty == Decimal("20")


def test_compute_size_zero_stop_rejected():
    with pytest.raises(RiskRejection):
        compute_size(
            equity=Decimal("10000"),
            account_risk_per_trade_percent=Decimal("1.0"),
            position_fraction=Decimal("0.30"),
            entry_price=Decimal("100"),
            stop_loss_price=Decimal("100"),
            qty_step=Decimal("0.001"),
        )


def test_max_leverage_by_mode(config):
    risk = config.risk
    assert max_leverage(entry_mode=EntryMode.PRE_BREAKOUT_SCOUT, atr_percent=Decimal("1"),
                        consecutive_losses=0, daily_loss_percent=Decimal("0"),
                        config=risk) == Decimal("6")
    assert max_leverage(entry_mode=EntryMode.BREAKOUT_CONFIRM, atr_percent=Decimal("1"),
                        consecutive_losses=0, daily_loss_percent=Decimal("0"),
                        config=risk) == Decimal("9")
    assert max_leverage(entry_mode=EntryMode.RETEST_CONFIRM, atr_percent=Decimal("1"),
                        consecutive_losses=0, daily_loss_percent=Decimal("0"),
                        config=risk) == Decimal("10")


def test_max_leverage_derisk_rules(config):
    risk = config.risk
    # high ATR caps to 5
    assert max_leverage(entry_mode=EntryMode.RETEST_CONFIRM, atr_percent=Decimal("4.0"),
                        consecutive_losses=0, daily_loss_percent=Decimal("0"),
                        config=risk) == Decimal("5")
    # consecutive losses cap to 3
    assert max_leverage(entry_mode=EntryMode.RETEST_CONFIRM, atr_percent=Decimal("1"),
                        consecutive_losses=2, daily_loss_percent=Decimal("0"),
                        config=risk) == Decimal("3")
    # daily loss caps to 2
    assert max_leverage(entry_mode=EntryMode.RETEST_CONFIRM, atr_percent=Decimal("1"),
                        consecutive_losses=0, daily_loss_percent=Decimal("3.0"),
                        config=risk) == Decimal("2")


def test_choose_leverage():
    assert choose_leverage(notional=Decimal("3000"), equity=Decimal("10000"),
                           max_lev=Decimal("6"), min_lev=Decimal("1")) == Decimal("1")
    assert choose_leverage(notional=Decimal("70000"), equity=Decimal("10000"),
                           max_lev=Decimal("5"), min_lev=Decimal("1")) == Decimal("5")
    assert choose_leverage(notional=Decimal("25000"), equity=Decimal("10000"),
                           max_lev=Decimal("6"), min_lev=Decimal("1")) == Decimal("3")


def test_levels():
    sl = stop_loss_price(Decimal("100"), Decimal("1"), Decimal("1.0"), PositionSide.LONG)
    assert sl == Decimal("99")
    tp = take_profit_price(Decimal("100"), sl, PositionSide.LONG, Decimal("2.0"))
    assert tp == Decimal("102")
    sl_s = stop_loss_price(Decimal("100"), Decimal("1"), Decimal("1.0"), PositionSide.SHORT)
    assert sl_s == Decimal("101")
    tp_s = take_profit_price(Decimal("100"), sl_s, PositionSide.SHORT, Decimal("2.0"))
    assert tp_s == Decimal("98")


def test_estimate_liq_price():
    liq = estimate_liq_price(Decimal("100"), Decimal("10"), PositionSide.LONG)
    # 100*(1 - 0.1 + 0.005) = 90.5
    assert liq == Decimal("90.5")
