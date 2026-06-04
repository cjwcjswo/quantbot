"""Core domain models (Decimal-based DTOs).

All prices and quantities use :class:`decimal.Decimal` to avoid float rounding
error in money math (impl doc Phase 1: "Decimal 기반 수량/가격 계산").
"""

from packages.core.models.exchange import (
    ExchangeOrder,
    ExchangeOrderResult,
    ExchangePosition,
    OrderRequest,
    PositionTpSlState,
    TradingStopRequest,
    TradingStopResult,
)
from packages.core.models.market import (
    Candle,
    MarketTicker,
    OrderBook,
    OrderBookLevel,
    SymbolMeta,
    WalletBalance,
)
from packages.core.models.trading import (
    Fill,
    IndicatorSnapshot,
    Order,
    Position,
    Signal,
)

__all__ = [
    # market
    "Candle",
    "MarketTicker",
    "OrderBook",
    "OrderBookLevel",
    "SymbolMeta",
    "WalletBalance",
    # exchange
    "ExchangeOrder",
    "ExchangeOrderResult",
    "ExchangePosition",
    "OrderRequest",
    "PositionTpSlState",
    "TradingStopRequest",
    "TradingStopResult",
    # trading
    "Fill",
    "IndicatorSnapshot",
    "Order",
    "Position",
    "Signal",
]
