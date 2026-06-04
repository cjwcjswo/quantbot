"""Tests for PaperExecutionEngine virtual fills (impl doc §2.1)."""

from decimal import Decimal

from packages.core.enums import Side
from packages.execution import PaperExecutionEngine


def _engine(config):
    return PaperExecutionEngine(config)


def test_buy_fill_price_includes_slippage(config):
    eng = _engine(config)
    fill = eng.execute_market("BTCUSDT", Side.BUY, Decimal("1"),
                              best_bid=Decimal("99"), best_ask=Decimal("100"))
    # 100 * (1 + 0.03/100) = 100.03
    assert fill.price == Decimal("100.03")
    # fee = 100.03 * 1 * 0.055/100
    assert fill.fee == Decimal("100.03") * Decimal("0.00055")


def test_sell_fill_price_includes_slippage(config):
    eng = _engine(config)
    fill = eng.execute_market("BTCUSDT", Side.SELL, Decimal("1"),
                              best_bid=Decimal("100"), best_ask=Decimal("101"))
    # 100 * (1 - 0.03/100) = 99.97
    assert fill.price == Decimal("99.97")


def test_round_trip_realizes_pnl(config):
    eng = _engine(config)
    start = eng.balance
    eng.execute_market("BTCUSDT", Side.BUY, Decimal("1"),
                       best_bid=Decimal("99"), best_ask=Decimal("100"))
    size, avg = eng.position("BTCUSDT")
    assert size == Decimal("1")
    assert avg == Decimal("100.03")

    fill = eng.execute_market("BTCUSDT", Side.SELL, Decimal("1"),
                              best_bid=Decimal("110"), best_ask=Decimal("111"))
    # exit price 110*(1-0.0003)=109.967; realized = (109.967 - 100.03)*1
    assert fill.realized_pnl == Decimal("109.967") - Decimal("100.03")
    assert eng.position("BTCUSDT") == (Decimal("0"), Decimal("0"))
    assert eng.balance > start  # net profit after fees


def test_partial_reduce_keeps_avg(config):
    eng = _engine(config)
    eng.execute_market("BTCUSDT", Side.BUY, Decimal("2"),
                       best_bid=Decimal("99"), best_ask=Decimal("100"))
    eng.execute_market("BTCUSDT", Side.SELL, Decimal("1"),
                       best_bid=Decimal("105"), best_ask=Decimal("106"))
    size, avg = eng.position("BTCUSDT")
    assert size == Decimal("1")
    assert avg == Decimal("100.03")  # reduction keeps original entry avg


def test_wallet_includes_unrealized(config):
    eng = _engine(config)
    eng.execute_market("BTCUSDT", Side.BUY, Decimal("1"),
                       best_bid=Decimal("99"), best_ask=Decimal("100"))
    w = eng.wallet({"BTCUSDT": Decimal("110")})
    assert w.unrealized_pnl == (Decimal("110") - Decimal("100.03")) * Decimal("1")
    assert w.equity == eng.balance + w.unrealized_pnl
