"""Deterministic in-memory ExchangeGateway for unit tests and the PAPER e2e harness.

It satisfies the ExchangeGateway protocol with no network access. Market data
(instruments / tickers / klines / orderbooks) is injected by the test; orders
fill immediately at a configurable ratio and update in-memory positions.
"""

from __future__ import annotations

from decimal import Decimal

from packages.core.enums import OrderStatus, OrderType, PositionSide, Side
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
    WalletBalance,
)


class FakeGateway:
    """In-memory exchange. Configure data via the ``set_*`` helpers."""

    def __init__(self, *, equity: Decimal = Decimal("10000")) -> None:
        self.instruments: list[SymbolMeta] = []
        self.tickers: dict[str, MarketTicker] = {}
        self.klines: dict[tuple[str, str], list[Candle]] = {}
        self.orderbooks: dict[str, OrderBook] = {}
        self.positions: dict[str, ExchangePosition] = {}
        self.open_orders: list[ExchangeOrder] = []
        self.leverage: dict[str, Decimal] = {}
        self._tpsl: dict[str, tuple[Decimal | None, Decimal | None]] = {}
        self._wallet = WalletBalance(
            coin="USDT",
            equity=equity,
            available_balance=equity,
            wallet_balance=equity,
        )
        # call log for assertions
        self.ticker_calls: int = 0
        self.placed_orders: list[OrderRequest] = []
        self.trading_stops: list = []
        self.cancelled: list[tuple[str, str | None, str | None]] = []
        self.kline_calls: list[tuple[str, str, int]] = []
        self.orderbook_calls: list[tuple[str, int]] = []
        # behavior knobs
        self.fill_ratio: Decimal = Decimal("1")  # fraction of qty filled
        self.disable_tpsl: bool = False  # when True, set_trading_stop is a no-op
        self.tpsl_override_on_set: tuple[Decimal | None, Decimal | None] | None = None
        self.server_time_ms: int = 0  # for clock-sync tests
        self._order_seq = 0

    async def get_server_time(self) -> int:
        return self.server_time_ms

    # ---- test configuration helpers ------------------------------------ #
    def set_instruments(self, instruments: list[SymbolMeta]) -> None:
        self.instruments = instruments

    def set_ticker(self, ticker: MarketTicker) -> None:
        self.tickers[ticker.symbol] = ticker

    def set_kline(self, symbol: str, interval: str, candles: list[Candle]) -> None:
        self.klines[(symbol, interval)] = candles

    def set_orderbook(self, ob: OrderBook) -> None:
        self.orderbooks[ob.symbol] = ob

    def set_position(self, position: ExchangePosition) -> None:
        self.positions[position.symbol] = position

    # ---- ExchangeGateway protocol -------------------------------------- #
    async def load_instruments(self) -> list[SymbolMeta]:
        return list(self.instruments)

    async def get_tickers(self) -> list[MarketTicker]:
        self.ticker_calls += 1
        return list(self.tickers.values())

    async def get_kline(self, symbol: str, interval: str, limit: int) -> list[Candle]:
        self.kline_calls.append((symbol, interval, limit))
        return list(self.klines.get((symbol, interval), []))[-limit:]

    async def get_orderbook(self, symbol: str, depth: int) -> OrderBook:
        self.orderbook_calls.append((symbol, depth))
        return self.orderbooks.get(symbol, OrderBook(symbol=symbol))

    async def get_wallet_balance(self) -> WalletBalance:
        return self._wallet

    async def get_positions(self) -> list[ExchangePosition]:
        return [p for p in self.positions.values() if p.side is not None]

    async def get_open_orders(
        self, symbol: str | None = None
    ) -> list[ExchangeOrder]:
        if symbol is None:
            return list(self.open_orders)
        return [o for o in self.open_orders if o.symbol == symbol]

    async def get_order(
        self, symbol: str, order_id: str | None, client_order_id: str | None
    ) -> ExchangeOrder | None:
        for order in await self.get_open_orders(symbol):
            if order_id and order.order_id == order_id:
                return order
            if client_order_id and order.client_order_id == client_order_id:
                return order
        return None

    async def set_leverage(self, symbol: str, leverage: Decimal) -> None:
        self.leverage[symbol] = leverage

    async def place_order(self, request: OrderRequest) -> ExchangeOrderResult:
        self.placed_orders.append(request)
        self._order_seq += 1
        order_id = f"fake-{self._order_seq}"

        fill_qty = (request.qty * self.fill_ratio).quantize(Decimal("0.00000001"))
        fill_price = request.price or self.tickers.get(
            request.symbol,
            MarketTicker(
                symbol=request.symbol,
                last_price=Decimal("0"),
                bid_price=Decimal("0"),
                ask_price=Decimal("0"),
            ),
        ).last_price

        if fill_qty > 0:
            self._apply_fill(request, fill_qty, fill_price)
            self._apply_attached_tpsl(request)

        status = (
            OrderStatus.FILLED
            if self.fill_ratio >= 1
            else OrderStatus.PARTIALLY_FILLED
            if fill_qty > 0
            else OrderStatus.NEW
        )
        return ExchangeOrderResult(
            symbol=request.symbol,
            order_id=order_id,
            client_order_id=request.client_order_id,
            status=status,
            filled_qty=fill_qty,
            avg_fill_price=fill_price if fill_qty > 0 else None,
        )

    def _apply_fill(
        self, request: OrderRequest, qty: Decimal, price: Decimal
    ) -> None:
        existing = self.positions.get(request.symbol)
        signed = qty if request.side is Side.BUY else -qty
        prev_size = Decimal("0")
        prev_side = None
        if existing and existing.side is not None:
            prev_side = existing.side
            prev_size = (
                existing.size
                if existing.side is PositionSide.LONG
                else -existing.size
            )
        new_signed = prev_size + signed

        if new_signed == 0:
            self.positions[request.symbol] = ExchangePosition(
                symbol=request.symbol,
                side=None,
                size=Decimal("0"),
                avg_price=Decimal("0"),
            )
            self._tpsl.pop(request.symbol, None)
            return

        new_side = PositionSide.LONG if new_signed > 0 else PositionSide.SHORT
        increasing_same_dir = (
            existing is not None
            and prev_side == new_side
            and (signed > 0) == (prev_size > 0)
        )
        reducing_same_dir = (
            existing is not None and prev_side == new_side and not increasing_same_dir
        )
        if increasing_same_dir:
            # Weighted average when adding exposure in the same direction.
            total = existing.size + qty
            avg = (existing.avg_price * existing.size + price * qty) / total
        elif reducing_same_dir:
            # Partial reduction keeps the original entry average.
            avg = existing.avg_price
        else:
            # Flat -> new, or crossed through zero to the opposite side.
            avg = price
        self.positions[request.symbol] = ExchangePosition(
            symbol=request.symbol,
            side=new_side,
            size=abs(new_signed),
            avg_price=avg,
            leverage=self.leverage.get(request.symbol, Decimal("1")),
        )

    def _apply_attached_tpsl(self, request: OrderRequest) -> None:
        if request.reduce_only or self.disable_tpsl:
            return
        if request.take_profit is None and request.stop_loss is None:
            return
        self._tpsl[request.symbol] = (request.take_profit, request.stop_loss)
        pos = self.positions.get(request.symbol)
        if pos and pos.side is not None:
            self.positions[request.symbol] = pos.model_copy(
                update={
                    "take_profit": request.take_profit,
                    "stop_loss": request.stop_loss,
                }
            )

    async def cancel_order(
        self, symbol: str, order_id: str | None, client_order_id: str | None
    ) -> None:
        self.cancelled.append((symbol, order_id, client_order_id))
        self.open_orders = [
            o
            for o in self.open_orders
            if not (
                o.symbol == symbol
                and (order_id is None or o.order_id == order_id)
                and (client_order_id is None or o.client_order_id == client_order_id)
            )
        ]

    async def set_trading_stop(self, request):  # TradingStopRequest
        from packages.core.models import TradingStopResult

        self.trading_stops.append(request)
        if self.disable_tpsl:
            # Simulate the exchange not registering TP/SL (verify will fail).
            return TradingStopResult(symbol=request.symbol, success=True)
        tp, sl = self.tpsl_override_on_set or (request.take_profit, request.stop_loss)
        self._tpsl[request.symbol] = (tp, sl)
        pos = self.positions.get(request.symbol)
        if pos and pos.side is not None:
            self.positions[request.symbol] = pos.model_copy(
                update={
                    "take_profit": tp,
                    "stop_loss": sl,
                }
            )
        from packages.core.models import TradingStopResult

        return TradingStopResult(symbol=request.symbol, success=True)

    async def get_position_tpsl(self, symbol: str) -> PositionTpSlState:
        tp, sl = self._tpsl.get(symbol, (None, None))
        return PositionTpSlState(symbol=symbol, take_profit=tp, stop_loss=sl)
