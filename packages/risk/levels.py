"""Stop-loss / take-profit / liquidation price math (impl doc §5.4, §13.4).

Long:
    stop_loss  = entry - ATR * stop_atr
    take_profit = entry + (entry - stop_loss) * R
Short:
    stop_loss  = entry + ATR * stop_atr
    take_profit = entry - (stop_loss - entry) * R

The liquidation price is *estimated* from leverage for the pre-trade guard; the
real liq price is read back from Bybit after entry during reconciliation.
"""

from __future__ import annotations

from decimal import Decimal

from packages.core.enums import PositionSide


def stop_loss_price(
    entry: Decimal, atr: Decimal, stop_atr: Decimal, side: PositionSide
) -> Decimal:
    offset = atr * stop_atr
    if side == PositionSide.LONG:
        return entry - offset
    return entry + offset


def take_profit_price(
    entry: Decimal, stop_loss: Decimal, side: PositionSide, take_profit_r: Decimal
) -> Decimal:
    if side == PositionSide.LONG:
        return entry + (entry - stop_loss) * take_profit_r
    return entry - (stop_loss - entry) * take_profit_r


def estimate_liq_price(
    entry: Decimal,
    leverage: Decimal,
    side: PositionSide,
    maintenance_margin_rate: Decimal = Decimal("0.005"),
) -> Decimal:
    """Approximate isolated-margin liquidation price.

    long  ~ entry * (1 - 1/leverage + mmr)
    short ~ entry * (1 + 1/leverage - mmr)
    """
    if leverage <= 0:
        leverage = Decimal(1)
    inv = Decimal(1) / leverage
    if side == PositionSide.LONG:
        return entry * (Decimal(1) - inv + maintenance_margin_rate)
    return entry * (Decimal(1) + inv - maintenance_margin_rate)
