"""ExchangeGateway protocol (impl doc §6.2).

Every Bybit interaction in the system goes through an implementation of this
protocol. No other module may import ``pybit`` directly (arch doc §6.6, §13).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

from packages.core.models import (
    Candle,
    ExchangeOrder,
    ExchangeOrderResult,
    ExchangePosition,
    MarketTicker,
    OrderBook,
    OrderRequest,
    PositionTpSlState,
    SymbolMeta,
    TradingStopRequest,
    TradingStopResult,
    WalletBalance,
)


@runtime_checkable
class ExchangeGateway(Protocol):
    """Abstraction over the exchange (Bybit V5).

    The signature mirrors impl doc §6.2 exactly. Implementations: the live
    ``BybitExchangeGateway`` and the deterministic ``FakeGateway`` used in tests
    and the PAPER end-to-end harness.
    """

    async def load_instruments(self) -> list[SymbolMeta]: ...

    async def get_tickers(self) -> list[MarketTicker]: ...

    async def get_kline(
        self, symbol: str, interval: str, limit: int
    ) -> list[Candle]: ...

    async def get_orderbook(self, symbol: str, depth: int) -> OrderBook: ...

    async def get_wallet_balance(self) -> WalletBalance: ...

    async def get_positions(self) -> list[ExchangePosition]: ...

    async def get_open_orders(
        self, symbol: str | None = None
    ) -> list[ExchangeOrder]: ...

    async def get_order(
        self, symbol: str, order_id: str | None, client_order_id: str | None
    ) -> ExchangeOrder | None: ...

    async def set_leverage(self, symbol: str, leverage: Decimal) -> None: ...

    async def place_order(self, request: OrderRequest) -> ExchangeOrderResult: ...

    async def cancel_order(
        self, symbol: str, order_id: str | None, client_order_id: str | None
    ) -> None: ...

    async def set_trading_stop(
        self, request: TradingStopRequest
    ) -> TradingStopResult: ...

    async def get_position_tpsl(self, symbol: str) -> PositionTpSlState: ...
