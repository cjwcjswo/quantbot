"""Exchange-facing request/response models used by ExchangeGateway (impl doc §6.2)."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from packages.core.enums import (
    OrderStatus,
    OrderType,
    PositionSide,
    Side,
    TimeInForce,
    TriggerBy,
)


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class _MutModel(BaseModel):
    model_config = ConfigDict(frozen=False)


class ExchangePosition(_Model):
    """A position as reported by the exchange (source of truth, arch doc §3.6)."""

    symbol: str
    side: PositionSide | None  # None => flat
    size: Decimal
    avg_price: Decimal
    leverage: Decimal = Decimal("1")
    liq_price: Decimal | None = None
    unrealized_pnl: Decimal = Decimal("0")
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    position_idx: int = 0


class ExchangeOrder(_Model):
    """An order as reported by the exchange (/v5/order/realtime)."""

    symbol: str
    order_id: str
    client_order_id: str | None
    side: Side
    order_type: str
    price: Decimal | None
    qty: Decimal
    cum_exec_qty: Decimal = Decimal("0")
    avg_price: Decimal | None = None
    status: OrderStatus = OrderStatus.UNKNOWN
    reduce_only: bool = False
    created_ms: int = 0


class OrderRequest(_MutModel):
    """A request to place an order via the gateway.

    ``order_type`` is the *internal* type. AGGRESSIVE_LIMIT is translated to a
    marketable LIMIT (IOC) by the gateway. New-entry MARKET is rejected in LIVE
    (impl doc §2.2). ``client_order_id`` provides idempotency (impl doc §17.1).
    """

    symbol: str
    side: Side
    order_type: OrderType
    qty: Decimal
    price: Decimal | None = None
    time_in_force: TimeInForce | None = None
    reduce_only: bool = False
    client_order_id: str | None = None


class ExchangeOrderResult(_Model):
    """Result of placing an order."""

    symbol: str
    order_id: str
    client_order_id: str | None
    status: OrderStatus
    filled_qty: Decimal = Decimal("0")
    avg_fill_price: Decimal | None = None
    raw: dict | None = None


class TradingStopRequest(_MutModel):
    """Request for /v5/position/trading-stop (Set Trading Stop, impl doc §5)."""

    symbol: str
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    tp_trigger_by: TriggerBy = TriggerBy.LAST_PRICE
    sl_trigger_by: TriggerBy = TriggerBy.LAST_PRICE
    tpsl_mode: str = "Full"
    position_idx: int = 0


class TradingStopResult(_Model):
    symbol: str
    success: bool
    raw: dict | None = None


class PositionTpSlState(_Model):
    """TP/SL state read back from the exchange for verification (impl doc §5.2)."""

    symbol: str
    take_profit: Decimal | None
    stop_loss: Decimal | None

    @property
    def has_tp(self) -> bool:
        return self.take_profit is not None and self.take_profit > 0

    @property
    def has_sl(self) -> bool:
        return self.stop_loss is not None and self.stop_loss > 0

    @property
    def is_protected(self) -> bool:
        """Both TP and SL present (impl doc §5.1 requires both)."""
        return self.has_tp and self.has_sl
