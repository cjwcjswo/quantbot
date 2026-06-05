"""Bybit V5 implementation of ExchangeGateway via the official ``pybit`` SDK.

``pybit`` is synchronous, so each call is executed in a worker thread
(``asyncio.to_thread``) wrapped with a rate limiter + exponential backoff.
Only this module imports ``pybit`` (arch doc §6.6).
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from packages.core.enums import (
    OrderStatus,
    OrderType,
    PositionSide,
    Side,
    TimeInForce,
)
from packages.core.errors import ExchangeError, OrderError
from packages.core.models import (
    Candle,
    ExchangeOrder,
    ExchangeOrderResult,
    ExchangePosition,
    MarketTicker,
    OrderBook,
    OrderBookLevel,
    OrderRequest,
    PositionTpSlState,
    SymbolMeta,
    TradingStopRequest,
    TradingStopResult,
    WalletBalance,
)
from packages.guards.rate_limit import RateLimiter, with_backoff

logger = logging.getLogger(__name__)

_BYBIT_ORDER_STATUS = {
    "New": OrderStatus.NEW,
    "PartiallyFilled": OrderStatus.PARTIALLY_FILLED,
    "Filled": OrderStatus.FILLED,
    "Cancelled": OrderStatus.CANCELLED,
    "Rejected": OrderStatus.REJECTED,
    "PartiallyFilledCanceled": OrderStatus.CANCELLED,
    "Deactivated": OrderStatus.CANCELLED,
    "Untriggered": OrderStatus.NEW,
    "Triggered": OrderStatus.NEW,
}


def _dec(value: object, default: str = "0") -> Decimal:
    """Parse a Bybit string field to Decimal, tolerating ''/None."""
    if value is None or value == "":
        return Decimal(default)
    return Decimal(str(value))


def _opt_dec(value: object) -> Decimal | None:
    if value is None or value == "" or value == "0":
        return None
    return Decimal(str(value))


def _is_order_missing_error(exc: Exception) -> bool:
    text = str(exc)
    return "ErrCode: 110001" in text or "retCode=110001" in text


def _is_leverage_unchanged_error(exc: Exception) -> bool:
    text = str(exc)
    return "ErrCode: 110043" in text or "retCode=110043" in text


class BybitExchangeGateway:
    """Concrete :class:`~packages.exchange.gateway.ExchangeGateway` for Bybit."""

    def __init__(
        self,
        *,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = False,
        category: str = "linear",
        account_type: str = "UNIFIED",
        quote_coin: str = "USDT",
        recv_window: int = 5000,
        rest_rate_per_sec: int = 5,
        order_rate_per_sec: int = 2,
        backoff_base_sec: float = 1.0,
        backoff_max_sec: float = 30.0,
    ) -> None:
        self._category = category
        self._account_type = account_type
        self._quote_coin = quote_coin
        self._testnet = testnet
        self._api_key = api_key
        self._api_secret = api_secret
        self._backoff_base = backoff_base_sec
        self._backoff_max = backoff_max_sec
        self._rest_limiter = RateLimiter(rest_rate_per_sec)
        self._order_limiter = RateLimiter(order_rate_per_sec)

        # Lazy import so the rest of the system (and tests using FakeGateway)
        # never require pybit to be importable.
        from pybit.unified_trading import HTTP

        self._http = HTTP(
            api_key=api_key,
            api_secret=api_secret,
            testnet=testnet,
            recv_window=recv_window,
        )

    # ------------------------------------------------------------------ #
    # internal helpers
    # ------------------------------------------------------------------ #
    async def _rest(self, fn, /, *args, **kwargs):
        async def call():
            async with self._rest_limiter:
                return await asyncio.to_thread(fn, *args, **kwargs)

        resp = await with_backoff(
            call, base_sec=self._backoff_base, max_sec=self._backoff_max
        )
        return self._unwrap(resp)

    async def _order_rest(self, fn, /, *args, **kwargs):
        async def call():
            async with self._order_limiter:
                return await asyncio.to_thread(fn, *args, **kwargs)

        resp = await with_backoff(
            call, retries=1, base_sec=self._backoff_base, max_sec=self._backoff_max
        )
        return self._unwrap(resp)

    @staticmethod
    def _unwrap(resp: dict) -> dict:
        ret_code = resp.get("retCode")
        if ret_code not in (0, None):
            raise ExchangeError(
                f"Bybit error retCode={ret_code} retMsg={resp.get('retMsg')}"
            )
        return resp.get("result") or {}

    # ------------------------------------------------------------------ #
    # market data
    # ------------------------------------------------------------------ #
    async def load_instruments(self) -> list[SymbolMeta]:
        result = await self._rest(
            self._http.get_instruments_info, category=self._category
        )
        out: list[SymbolMeta] = []
        for item in result.get("list", []):
            if item.get("quoteCoin") != self._quote_coin:
                continue
            lot = item.get("lotSizeFilter", {})
            price_f = item.get("priceFilter", {})
            lev_f = item.get("leverageFilter", {})
            out.append(
                SymbolMeta(
                    symbol=item["symbol"],
                    base_coin=item.get("baseCoin", ""),
                    quote_coin=item.get("quoteCoin", ""),
                    status=item.get("status", ""),
                    tick_size=_dec(price_f.get("tickSize"), "0.0001"),
                    qty_step=_dec(lot.get("qtyStep"), "0.001"),
                    min_order_qty=_dec(lot.get("minOrderQty")),
                    max_order_qty=_dec(lot.get("maxOrderQty")),
                    min_notional=_dec(lot.get("minNotionalValue")),
                    max_leverage=_dec(lev_f.get("maxLeverage"), "1"),
                    launch_time_ms=int(item["launchTime"])
                    if item.get("launchTime")
                    else None,
                )
            )
        return out

    async def get_tickers(self) -> list[MarketTicker]:
        result = await self._rest(self._http.get_tickers, category=self._category)
        out: list[MarketTicker] = []
        for item in result.get("list", []):
            out.append(
                MarketTicker(
                    symbol=item["symbol"],
                    last_price=_dec(item.get("lastPrice")),
                    bid_price=_dec(item.get("bid1Price")),
                    ask_price=_dec(item.get("ask1Price")),
                    turnover_24h=_dec(item.get("turnover24h")),
                    volume_24h=_dec(item.get("volume24h")),
                    funding_rate=_opt_dec(item.get("fundingRate")),
                    next_funding_time_ms=int(item["nextFundingTime"])
                    if item.get("nextFundingTime")
                    else None,
                )
            )
        return out

    async def get_kline(self, symbol: str, interval: str, limit: int) -> list[Candle]:
        result = await self._rest(
            self._http.get_kline,
            category=self._category,
            symbol=symbol,
            interval=interval,
            limit=limit,
        )
        candles: list[Candle] = []
        # Bybit returns newest-first; reverse to chronological order.
        for row in reversed(result.get("list", [])):
            candles.append(
                Candle(
                    symbol=symbol,
                    interval=interval,
                    open_time_ms=int(row[0]),
                    open=_dec(row[1]),
                    high=_dec(row[2]),
                    low=_dec(row[3]),
                    close=_dec(row[4]),
                    volume=_dec(row[5]),
                    turnover=_dec(row[6]) if len(row) > 6 else Decimal("0"),
                    confirmed=True,
                )
            )
        return candles

    # ------------------------------------------------------------------ #
    # WebSocket (live-only; impl doc §17.2). Bridges pybit's threaded
    # callbacks to model objects passed to the provided sinks.
    # ------------------------------------------------------------------ #
    def start_market_websocket(
        self,
        *,
        symbols: list[str],
        on_candle=None,
        on_ticker=None,
        on_disconnect=None,
        intervals: tuple[str, ...] = ("1", "5", "15"),
    ) -> None:
        from pybit.unified_trading import WebSocket

        self._ws = WebSocket(testnet=self._testnet, channel_type="linear")

        def _kline_cb(msg: dict) -> None:
            if on_candle is None:
                return
            topic = msg.get("topic", "")
            symbol = topic.split(".")[-1]
            for row in msg.get("data", []):
                try:
                    on_candle(
                        Candle(
                            symbol=symbol, interval=str(row.get("interval", "")),
                            open_time_ms=int(row["start"]),
                            open=_dec(row["open"]), high=_dec(row["high"]),
                            low=_dec(row["low"]), close=_dec(row["close"]),
                            volume=_dec(row.get("volume")),
                            turnover=_dec(row.get("turnover")),
                            confirmed=bool(row.get("confirm", False)),
                        )
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("ws kline map failed")

        def _ticker_cb(msg: dict) -> None:
            if on_ticker is None:
                return
            d = msg.get("data", {})
            try:
                on_ticker(
                    MarketTicker(
                        symbol=d["symbol"], last_price=_dec(d.get("lastPrice")),
                        bid_price=_dec(d.get("bid1Price")), ask_price=_dec(d.get("ask1Price")),
                        turnover_24h=_dec(d.get("turnover24h")),
                        volume_24h=_dec(d.get("volume24h")),
                        funding_rate=_opt_dec(d.get("fundingRate")),
                        next_funding_time_ms=int(d["nextFundingTime"])
                        if d.get("nextFundingTime") else None,
                    )
                )
            except Exception:  # noqa: BLE001
                logger.debug("ws ticker map failed")

        for symbol in symbols:
            self._ws.ticker_stream(symbol=symbol, callback=_ticker_cb)
            for interval in intervals:
                self._ws.kline_stream(interval=interval, symbol=symbol, callback=_kline_cb)
        self._ws_on_disconnect = on_disconnect

    def start_private_websocket(
        self,
        *,
        on_order=None,
        on_execution=None,
        on_position=None,
        on_disconnect=None,
    ) -> None:
        """Subscribe to private order/execution/position streams.

        Runtime callbacks deliberately receive raw pybit payloads; the runtime
        then schedules a source-of-truth reconciliation rather than trusting a
        partial private-stream projection.
        """
        if not self._api_key or not self._api_secret:
            logger.warning("private WebSocket unavailable: API credentials missing")
            return
        from pybit.unified_trading import WebSocket

        self._private_ws = WebSocket(
            testnet=self._testnet,
            channel_type="private",
            api_key=self._api_key,
            api_secret=self._api_secret,
        )
        if on_order is not None:
            self._private_ws.order_stream(callback=on_order)
        if on_execution is not None:
            self._private_ws.execution_stream(callback=on_execution)
        if on_position is not None:
            self._private_ws.position_stream(callback=on_position)
        self._private_ws_on_disconnect = on_disconnect

    async def get_server_time(self) -> int:
        """Bybit server time in ms (impl doc §7 clock_sync). Not in the Protocol."""
        result = await self._rest(self._http.get_server_time)
        nano = result.get("timeNano")
        if nano:
            return int(nano) // 1_000_000
        return int(result.get("timeSecond", "0")) * 1000

    async def get_orderbook(self, symbol: str, depth: int) -> OrderBook:
        result = await self._rest(
            self._http.get_orderbook,
            category=self._category,
            symbol=symbol,
            limit=depth,
        )
        bids = tuple(
            OrderBookLevel(price=_dec(p), size=_dec(s))
            for p, s in result.get("b", [])
        )
        asks = tuple(
            OrderBookLevel(price=_dec(p), size=_dec(s))
            for p, s in result.get("a", [])
        )
        return OrderBook(
            symbol=symbol, bids=bids, asks=asks, ts_ms=int(result.get("ts", 0))
        )

    # ------------------------------------------------------------------ #
    # account / position
    # ------------------------------------------------------------------ #
    async def get_wallet_balance(self) -> WalletBalance:
        result = await self._rest(
            self._http.get_wallet_balance,
            accountType=self._account_type,
            coin=self._quote_coin,
        )
        rows = result.get("list", [])
        if not rows:
            raise ExchangeError("Empty wallet balance response")
        account = rows[0]
        coin_rows = account.get("coin", [])
        coin = next(
            (c for c in coin_rows if c.get("coin") == self._quote_coin),
            coin_rows[0] if coin_rows else {},
        )
        return WalletBalance(
            coin=coin.get("coin", self._quote_coin),
            equity=_dec(coin.get("equity")),
            available_balance=_dec(
                coin.get("availableToWithdraw") or coin.get("walletBalance")
            ),
            wallet_balance=_dec(coin.get("walletBalance")),
            unrealized_pnl=_dec(coin.get("unrealisedPnl")),
        )

    async def get_positions(self) -> list[ExchangePosition]:
        result = await self._rest(
            self._http.get_positions,
            category=self._category,
            settleCoin=self._quote_coin,
        )
        out: list[ExchangePosition] = []
        for item in result.get("list", []):
            size = _dec(item.get("size"))
            raw_side = item.get("side")
            if size == 0 or raw_side not in ("Buy", "Sell"):
                side = None
            else:
                side = PositionSide.LONG if raw_side == "Buy" else PositionSide.SHORT
            out.append(
                ExchangePosition(
                    symbol=item["symbol"],
                    side=side,
                    size=size,
                    avg_price=_dec(item.get("avgPrice")),
                    leverage=_dec(item.get("leverage"), "1"),
                    liq_price=_opt_dec(item.get("liqPrice")),
                    unrealized_pnl=_dec(item.get("unrealisedPnl")),
                    take_profit=_opt_dec(item.get("takeProfit")),
                    stop_loss=_opt_dec(item.get("stopLoss")),
                    position_idx=int(item.get("positionIdx", 0)),
                )
            )
        return out

    async def get_open_orders(
        self, symbol: str | None = None
    ) -> list[ExchangeOrder]:
        kwargs = {"category": self._category}
        if symbol:
            kwargs["symbol"] = symbol
        else:
            kwargs["settleCoin"] = self._quote_coin
        result = await self._rest(self._http.get_open_orders, **kwargs)
        out: list[ExchangeOrder] = []
        for item in result.get("list", []):
            out.append(
                ExchangeOrder(
                    symbol=item["symbol"],
                    order_id=item.get("orderId", ""),
                    client_order_id=item.get("orderLinkId") or None,
                    side=Side(item["side"]),
                    order_type=item.get("orderType", ""),
                    price=_opt_dec(item.get("price")),
                    qty=_dec(item.get("qty")),
                    cum_exec_qty=_dec(item.get("cumExecQty")),
                    avg_price=_opt_dec(item.get("avgPrice")),
                    status=_BYBIT_ORDER_STATUS.get(
                        item.get("orderStatus", ""), OrderStatus.UNKNOWN
                    ),
                    reduce_only=bool(item.get("reduceOnly", False)),
                    created_ms=int(item.get("createdTime", 0)),
                )
            )
        return out

    async def get_order(
        self, symbol: str, order_id: str | None, client_order_id: str | None
    ) -> ExchangeOrder | None:
        """Read a single recent order for fill resolution.

        Bybit create-order responses contain identifiers, not a complete fill
        snapshot. Query realtime first, then recent history for IOC/filled orders
        that may have disappeared from the open-order set.
        """
        params: dict[str, object] = {"category": self._category, "symbol": symbol}
        if order_id:
            params["orderId"] = order_id
        elif client_order_id:
            params["orderLinkId"] = client_order_id
        else:
            return None

        for method_name in ("get_open_orders", "get_order_history"):
            method = getattr(self._http, method_name, None)
            if method is None:
                continue
            try:
                result = await self._rest(method, **params)
            except Exception:
                logger.debug("Bybit %s lookup failed for %s", method_name, symbol)
                continue
            rows = result.get("list", [])
            if rows:
                return self._map_order(rows[0])
        return None

    async def set_leverage(self, symbol: str, leverage: Decimal) -> None:
        lev = str(leverage)
        params = {
            "category": self._category,
            "symbol": symbol,
            "buyLeverage": lev,
            "sellLeverage": lev,
        }

        async def call():
            async with self._rest_limiter:
                try:
                    return await asyncio.to_thread(self._http.set_leverage, **params)
                except Exception as exc:
                    if _is_leverage_unchanged_error(exc):
                        logger.info("set_leverage already %s for %s", lev, symbol)
                        return {"retCode": 0, "result": {}}
                    raise

        resp = await with_backoff(
            call, base_sec=self._backoff_base, max_sec=self._backoff_max
        )
        self._unwrap(resp)

    def _map_order(self, item: dict) -> ExchangeOrder:
        return ExchangeOrder(
            symbol=item["symbol"],
            order_id=item.get("orderId", ""),
            client_order_id=item.get("orderLinkId") or None,
            side=Side(item["side"]),
            order_type=item.get("orderType", ""),
            price=_opt_dec(item.get("price")),
            qty=_dec(item.get("qty")),
            cum_exec_qty=_dec(item.get("cumExecQty")),
            avg_price=_opt_dec(item.get("avgPrice")),
            status=_BYBIT_ORDER_STATUS.get(
                item.get("orderStatus", ""), OrderStatus.UNKNOWN
            ),
            reduce_only=bool(item.get("reduceOnly", False)),
            created_ms=int(item.get("createdTime", 0)),
        )

    # ------------------------------------------------------------------ #
    # orders
    # ------------------------------------------------------------------ #
    async def place_order(self, request: OrderRequest) -> ExchangeOrderResult:
        order_type, tif = self._map_order_type(request)
        params: dict[str, object] = {
            "category": self._category,
            "symbol": request.symbol,
            "side": request.side.value,
            "orderType": order_type,
            "qty": str(request.qty),
            "reduceOnly": request.reduce_only,
        }
        if request.price is not None:
            params["price"] = str(request.price)
        if tif is not None:
            params["timeInForce"] = tif.value
        if request.client_order_id:
            params["orderLinkId"] = request.client_order_id

        result = await self._order_rest(self._http.place_order, **params)
        order_id = result.get("orderId", "")
        if not order_id:
            raise OrderError(f"place_order returned no orderId for {request.symbol}")
        return ExchangeOrderResult(
            symbol=request.symbol,
            order_id=order_id,
            client_order_id=result.get("orderLinkId") or request.client_order_id,
            status=OrderStatus.NEW,
            raw=result,
        )

    @staticmethod
    def _map_order_type(
        request: OrderRequest,
    ) -> tuple[str, TimeInForce | None]:
        """Translate internal OrderType to Bybit orderType + timeInForce."""
        if request.order_type is OrderType.MARKET:
            return "Market", None
        if request.order_type is OrderType.AGGRESSIVE_LIMIT:
            # Marketable limit, immediate-or-cancel (impl doc §12.4).
            return "Limit", request.time_in_force or TimeInForce.IOC
        # plain LIMIT
        return "Limit", request.time_in_force or TimeInForce.GTC

    async def cancel_order(
        self, symbol: str, order_id: str | None, client_order_id: str | None
    ) -> None:
        params: dict[str, object] = {"category": self._category, "symbol": symbol}
        if order_id:
            params["orderId"] = order_id
        elif client_order_id:
            params["orderLinkId"] = client_order_id
        else:
            raise OrderError("cancel_order requires order_id or client_order_id")

        async def call():
            async with self._order_limiter:
                try:
                    return await asyncio.to_thread(self._http.cancel_order, **params)
                except Exception as exc:
                    if _is_order_missing_error(exc):
                        logger.info("cancel_order already settled for %s", symbol)
                        return {"retCode": 0, "result": {}}
                    raise

        resp = await with_backoff(
            call, retries=1, base_sec=self._backoff_base, max_sec=self._backoff_max
        )
        self._unwrap(resp)

    # ------------------------------------------------------------------ #
    # TP/SL protection
    # ------------------------------------------------------------------ #
    async def set_trading_stop(
        self, request: TradingStopRequest
    ) -> TradingStopResult:
        params: dict[str, object] = {
            "category": self._category,
            "symbol": request.symbol,
            "tpslMode": request.tpsl_mode,
            "tpTriggerBy": request.tp_trigger_by.value,
            "slTriggerBy": request.sl_trigger_by.value,
            "positionIdx": request.position_idx,
        }
        if request.take_profit is not None:
            params["takeProfit"] = str(request.take_profit)
        if request.stop_loss is not None:
            params["stopLoss"] = str(request.stop_loss)
        result = await self._rest(self._http.set_trading_stop, **params)
        return TradingStopResult(symbol=request.symbol, success=True, raw=result)

    async def get_position_tpsl(self, symbol: str) -> PositionTpSlState:
        result = await self._rest(
            self._http.get_positions, category=self._category, symbol=symbol
        )
        rows = result.get("list", [])
        if not rows:
            return PositionTpSlState(symbol=symbol, take_profit=None, stop_loss=None)
        item = next(
            (
                row for row in rows
                if _dec(row.get("size")) > 0 and row.get("side") in ("Buy", "Sell")
            ),
            rows[0],
        )
        return PositionTpSlState(
            symbol=symbol,
            take_profit=_opt_dec(item.get("takeProfit")),
            stop_loss=_opt_dec(item.get("stopLoss")),
        )
