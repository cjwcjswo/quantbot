"""Position sizing (impl doc §13.1).

```
base_risk_usdt       = equity * account_risk_per_trade_percent / 100
entry_mode_risk_usdt = base_risk_usdt * position_fraction
stop_distance_percent = abs(entry - stop_loss) / entry
position_notional    = entry_mode_risk_usdt / stop_distance_percent
position_notional    = max(position_notional, target_notional)  # when configured
qty                  = position_notional / entry
```
qty is floored to ``qtyStep``. A leverage cap may bound ``position_notional``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from packages.core.errors import RiskRejection
from packages.universe import round_qty_down


@dataclass(frozen=True)
class SizingResult:
    qty: Decimal
    notional: Decimal
    stop_distance_percent: Decimal
    risk_usdt: Decimal  # actual risk after rounding = qty * |entry - stop|


def compute_size(
    *,
    equity: Decimal,
    account_risk_per_trade_percent: Decimal,
    position_fraction: Decimal,
    entry_price: Decimal,
    stop_loss_price: Decimal,
    qty_step: Decimal,
    max_notional: Decimal | None = None,
    target_notional: Decimal | None = None,
) -> SizingResult:
    if entry_price <= 0:
        raise RiskRejection("INVALID_ENTRY_PRICE", "entry price must be positive")
    stop_distance = abs(entry_price - stop_loss_price)
    if stop_distance <= 0:
        raise RiskRejection("ZERO_STOP_DISTANCE", "stop equals entry")

    base_risk = equity * account_risk_per_trade_percent / Decimal(100)
    mode_risk = base_risk * position_fraction
    stop_distance_percent = stop_distance / entry_price
    notional = mode_risk / stop_distance_percent
    if target_notional is not None and target_notional > notional:
        notional = target_notional
    if max_notional is not None and notional > max_notional:
        notional = max_notional

    qty = round_qty_down(notional / entry_price, qty_step)
    notional = qty * entry_price
    risk_usdt = qty * stop_distance
    return SizingResult(
        qty=qty,
        notional=notional,
        stop_distance_percent=stop_distance_percent,
        risk_usdt=risk_usdt,
    )
