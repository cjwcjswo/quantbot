"""PaperExecutionEngine: virtual market-order fills (impl doc §2.1, arch doc §6.9).

PAPER uses real Bybit market data but simulates every order as an immediate
market fill against best bid/ask with configured slippage + taker fee. It never
touches the real exchange. Strategy / risk / position flows are identical to LIVE.

```
BUY  fill = best_ask * (1 + slippage% / 100)
SELL fill = best_bid * (1 - slippage% / 100)
fee = fill_price * qty * taker_fee% / 100
```
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from packages.config.settings import AppConfig
from packages.core.enums import Side
from packages.core.models import WalletBalance


@dataclass(frozen=True)
class PaperFill:
    symbol: str
    side: Side
    price: Decimal
    qty: Decimal
    fee: Decimal
    realized_pnl: Decimal


def _sign(x: Decimal) -> int:
    return (x > 0) - (x < 0)


class PaperExecutionEngine:
    def __init__(self, config: AppConfig) -> None:
        self.configure(config)
        self.balance = Decimal(str(config.paper.initial_balance_usdt))
        # symbol -> (signed_size, avg_price)
        self._net: dict[str, tuple[Decimal, Decimal]] = {}

    def configure(self, config: AppConfig) -> None:
        p = config.paper
        self.slippage = Decimal(str(p.market_slippage_percent))
        self.fee_pct = Decimal(str(p.taker_fee_percent))

    def fill_price(self, side: Side, best_bid: Decimal, best_ask: Decimal) -> Decimal:
        factor = self.slippage / Decimal(100)
        if side == Side.BUY:
            return best_ask * (Decimal(1) + factor)
        return best_bid * (Decimal(1) - factor)

    def execute_market(
        self, symbol: str, side: Side, qty: Decimal, best_bid: Decimal, best_ask: Decimal
    ) -> PaperFill:
        price = self.fill_price(side, best_bid, best_ask)
        fee = price * qty * self.fee_pct / Decimal(100)
        realized = self._apply(symbol, side, qty, price)
        self.balance += realized - fee
        return PaperFill(symbol, side, price, qty, fee, realized)

    def _apply(self, symbol: str, side: Side, qty: Decimal, price: Decimal) -> Decimal:
        signed = qty if side == Side.BUY else -qty
        cur_size, cur_avg = self._net.get(symbol, (Decimal(0), Decimal(0)))
        new_size = cur_size + signed

        realized = Decimal(0)
        reducing = cur_size != 0 and _sign(signed) != _sign(cur_size)
        if reducing:
            reduce_qty = min(qty, abs(cur_size))
            direction = Decimal(1) if cur_size > 0 else Decimal(-1)
            realized = (price - cur_avg) * reduce_qty * direction

        if new_size == 0:
            avg = Decimal(0)
        elif cur_size != 0 and _sign(new_size) == _sign(cur_size):
            if abs(new_size) > abs(cur_size):  # increasing same direction
                avg = (cur_avg * abs(cur_size) + price * qty) / abs(new_size)
            else:  # reducing, keep avg
                avg = cur_avg
        else:  # opened from flat, or crossed through zero
            avg = price

        self._net[symbol] = (new_size, avg)
        return realized

    # ---- introspection ------------------------------------------------- #
    def position(self, symbol: str) -> tuple[Decimal, Decimal]:
        """(signed_size, avg_price); size 0 == flat."""
        return self._net.get(symbol, (Decimal(0), Decimal(0)))

    def unrealized(self, symbol: str, mark_price: Decimal) -> Decimal:
        size, avg = self.position(symbol)
        return (mark_price - avg) * size

    def wallet(self, mark_prices: dict[str, Decimal] | None = None) -> WalletBalance:
        upnl = Decimal(0)
        if mark_prices:
            for sym, mark in mark_prices.items():
                upnl += self.unrealized(sym, mark)
        return WalletBalance(
            coin="USDT",
            equity=self.balance + upnl,
            available_balance=self.balance,
            wallet_balance=self.balance,
            unrealized_pnl=upnl,
        )
