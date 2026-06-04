"""Daily PnL (impl doc §18).

```
daily_net_pnl = realized_pnl + unrealized_pnl - fees - funding_fees
```
Unrealized is marked from the latest price per open position.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from packages.core.enums import PositionSide, PositionStatus
from packages.core.models import Position


@dataclass(frozen=True)
class PnlSnapshot:
    realized: Decimal
    unrealized: Decimal
    fees: Decimal
    funding: Decimal
    net: Decimal


def compute_pnl(
    positions: list[Position],
    mark_prices: dict[str, Decimal],
    *,
    funding: Decimal = Decimal(0),
) -> PnlSnapshot:
    realized = Decimal(0)
    unrealized = Decimal(0)
    fees = Decimal(0)
    for p in positions:
        realized += p.realized_pnl
        fees += p.fees_paid
        if p.status == PositionStatus.ACTIVE:
            mark = mark_prices.get(p.symbol)
            if mark is not None:
                direction = Decimal(1) if p.side == PositionSide.LONG else Decimal(-1)
                unrealized += (mark - p.avg_entry_price) * p.qty * direction
    net = realized + unrealized - fees - funding
    return PnlSnapshot(
        realized=realized, unrealized=unrealized, fees=fees, funding=funding, net=net
    )


def daily_loss_percent(snapshot: PnlSnapshot, equity: Decimal) -> Decimal:
    """Positive when losing (impl doc §13.3 / §7 use loss as a positive percent)."""
    if equity <= 0:
        return Decimal(0)
    return -snapshot.net / equity * Decimal(100)
