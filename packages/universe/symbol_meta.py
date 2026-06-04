"""Order quantity / price rounding to exchange increments (impl doc §13.1).

Quantity is floored to ``qtyStep``; price is rounded to the nearest ``tickSize``.
Helpers also check ``minOrderQty`` and ``minNotional``.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from packages.core.models import SymbolMeta


def round_qty_down(qty: Decimal, step: Decimal) -> Decimal:
    """Floor ``qty`` to a multiple of ``step`` (never round up an order size)."""
    if step <= 0:
        return qty
    steps = (qty / step).to_integral_value(rounding=ROUND_DOWN)
    return steps * step


def round_price_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    """Round ``price`` to the nearest ``tick``."""
    if tick <= 0:
        return price
    ticks = (price / tick).to_integral_value(rounding=ROUND_HALF_UP)
    return ticks * tick


def meets_min_qty(qty: Decimal, meta: SymbolMeta) -> bool:
    return qty >= meta.min_order_qty and qty > 0


def meets_min_notional(qty: Decimal, price: Decimal, meta: SymbolMeta) -> bool:
    if meta.min_notional <= 0:
        return True
    return qty * price >= meta.min_notional
