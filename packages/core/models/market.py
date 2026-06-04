"""Market data models: instrument metadata, ticker, candle, orderbook, balance."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class SymbolMeta(_Model):
    """Instrument metadata from /v5/market/instruments-info.

    Used to round order qty/price to exchange-legal increments (impl doc §13.1).
    """

    symbol: str
    base_coin: str
    quote_coin: str
    status: str  # e.g. "Trading"
    tick_size: Decimal  # price increment
    qty_step: Decimal  # quantity increment
    min_order_qty: Decimal
    max_order_qty: Decimal
    min_notional: Decimal = Decimal("0")
    max_leverage: Decimal = Decimal("1")
    launch_time_ms: int | None = None


class MarketTicker(_Model):
    """Latest ticker snapshot from /v5/market/tickers."""

    symbol: str
    last_price: Decimal
    bid_price: Decimal
    ask_price: Decimal
    turnover_24h: Decimal = Decimal("0")
    volume_24h: Decimal = Decimal("0")
    funding_rate: Decimal | None = None
    next_funding_time_ms: int | None = None
    ts_ms: int = 0  # exchange timestamp of this snapshot


class Candle(_Model):
    """A single OHLCV candle for one timeframe.

    ``confirmed`` distinguishes a completed candle from the in-progress one
    (impl doc CandleStore: "완성 캔들/진행 중 캔들 구분").
    """

    symbol: str
    interval: str  # "1", "5", "15" (minutes), Bybit kline interval strings
    open_time_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal = Decimal("0")
    confirmed: bool = True


class OrderBookLevel(_Model):
    price: Decimal
    size: Decimal


class OrderBook(_Model):
    symbol: str
    bids: tuple[OrderBookLevel, ...] = Field(default_factory=tuple)
    asks: tuple[OrderBookLevel, ...] = Field(default_factory=tuple)
    ts_ms: int = 0

    @property
    def best_bid(self) -> Decimal | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        return self.asks[0].price if self.asks else None


class WalletBalance(_Model):
    """Account balance from /v5/account/wallet-balance (or PAPER virtual)."""

    coin: str
    equity: Decimal
    available_balance: Decimal
    wallet_balance: Decimal
    unrealized_pnl: Decimal = Decimal("0")
