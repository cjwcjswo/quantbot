"""Pre-order Check (impl doc §16): final gate immediately before a LIVE order.

```
spread_percent <= 0.08
expected_slippage_percent <= 0.05
depth within +/-0.1% >= order_notional * 3
symbol status == Trading
clock drift <= 1000ms
```
Returns a reason string when the order must be blocked, else None.
"""

from __future__ import annotations

from decimal import Decimal

from packages.config.settings import AppConfig
from packages.core.models import OrderBook
from packages.guards.clock_sync import ClockSyncGuard
from packages.scanner import depth_usdt_within


class PreOrderCheck:
    def __init__(self, config: AppConfig) -> None:
        self.cfg = config
        self.max_spread = Decimal(str(config.scanner.max_spread_percent))
        self.max_slippage = Decimal(str(config.orders.max_slippage_percent))
        self.depth_multiple = Decimal(3)

    def check(
        self,
        *,
        orderbook: OrderBook,
        order_notional: Decimal,
        expected_slippage_percent: Decimal,
        symbol_status: str,
        clock: ClockSyncGuard,
    ) -> str | None:
        if self.cfg.symbol_status.block_if_status_not_trading and symbol_status != "Trading":
            return "SYMBOL_NOT_TRADING"

        if not clock.is_within_tolerance():
            return "CLOCK_DRIFT"

        bid, ask = orderbook.best_bid, orderbook.best_ask
        if bid is None or ask is None or bid <= 0 or ask <= 0:
            return "NO_ORDERBOOK"
        mid = (bid + ask) / Decimal(2)
        spread = (ask - bid) / mid * Decimal(100)
        if spread > self.max_spread:
            return "SPREAD_TOO_WIDE"

        if expected_slippage_percent > self.max_slippage:
            return "SLIPPAGE_TOO_HIGH"

        depth = depth_usdt_within(orderbook, Decimal("0.1"))
        if depth < order_notional * self.depth_multiple:
            return "INSUFFICIENT_DEPTH"

        return None
