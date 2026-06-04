"""Tests for PnL accounting (impl doc §18)."""

from decimal import Decimal

from packages.core.enums import PositionSide, PositionStatus
from packages.core.models import Position
from packages.pnl import compute_pnl, daily_loss_percent


def _pos(symbol, side, qty, entry, *, status=PositionStatus.ACTIVE, realized="0", fees="0"):
    return Position(
        symbol=symbol, side=side, status=status,
        qty=Decimal(qty), avg_entry_price=Decimal(entry),
        realized_pnl=Decimal(realized), fees_paid=Decimal(fees),
    )


def test_unrealized_long():
    p = _pos("BTCUSDT", PositionSide.LONG, "2", "100")
    snap = compute_pnl([p], {"BTCUSDT": Decimal("110")})
    assert snap.unrealized == Decimal("20")  # (110-100)*2
    assert snap.net == Decimal("20")


def test_unrealized_short():
    p = _pos("BTCUSDT", PositionSide.SHORT, "2", "100")
    snap = compute_pnl([p], {"BTCUSDT": Decimal("90")})
    assert snap.unrealized == Decimal("20")  # (90-100)*2*-1


def test_realized_fees_funding_net():
    p = _pos("BTCUSDT", PositionSide.LONG, "0", "100",
             status=PositionStatus.CLOSED, realized="50", fees="5")
    snap = compute_pnl([p], {}, funding=Decimal("3"))
    assert snap.realized == Decimal("50")
    assert snap.fees == Decimal("5")
    assert snap.net == Decimal("42")  # 50 + 0 - 5 - 3


def test_daily_loss_percent_positive_on_loss():
    p = _pos("BTCUSDT", PositionSide.LONG, "0", "100",
             status=PositionStatus.CLOSED, realized="-300")
    snap = compute_pnl([p], {})
    assert daily_loss_percent(snap, Decimal("10000")) == Decimal("3")
