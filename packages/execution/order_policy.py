"""Order-type policy (impl doc §12).

Entry order types by mode: Scout=LIMIT, Breakout=AGGRESSIVE_LIMIT (IOC),
Retest=LIMIT. New-entry MARKET is forbidden in LIVE (impl doc §2.2, §12.1).
"""

from __future__ import annotations

from decimal import Decimal

from packages.config.settings import OrdersSection
from packages.core.enums import EntryMode, OrderType, Side
from packages.core.errors import OrderError

_STR_TO_TYPE = {
    "LIMIT": OrderType.LIMIT,
    "AGGRESSIVE_LIMIT": OrderType.AGGRESSIVE_LIMIT,
    "MARKET": OrderType.MARKET,
}


def entry_order_type(entry_mode: EntryMode, config: OrdersSection) -> OrderType:
    mapping = {
        EntryMode.PRE_BREAKOUT_SCOUT: config.scout_order_type,
        EntryMode.BREAKOUT_CONFIRM: config.breakout_order_type,
        EntryMode.RETEST_CONFIRM: config.retest_order_type,
    }
    return _STR_TO_TYPE[mapping[entry_mode]]


def aggressive_limit_price(
    side: Side, best_ask: Decimal, best_bid: Decimal, slippage_percent: Decimal
) -> Decimal:
    """Marketable limit price (impl doc §12.4)."""
    factor = slippage_percent / Decimal(100)
    if side == Side.BUY:
        return best_ask * (Decimal(1) + factor)
    return best_bid * (Decimal(1) - factor)


def assert_live_new_entry_allowed(
    order_type: OrderType, reduce_only: bool, config: OrdersSection
) -> None:
    """Reject a LIVE new-entry MARKET order unless explicitly allowed."""
    if (
        order_type == OrderType.MARKET
        and not reduce_only
        and not config.live_new_entry_market_order_allowed
    ):
        raise OrderError("LIVE new-entry MARKET order is forbidden (impl doc §12.1)")
