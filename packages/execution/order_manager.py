"""OrderManager: executes RiskManager-approved LIVE orders (arch doc §6.20, impl §12).

Handles entry order typing, the AGGRESSIVE_LIMIT partial-fill policy (§12.4), the
LIMIT TTL / reorder / give-up policy (§12.3, no MARKET conversion), reduce-only
exits (§12.2), idempotent ``client_order_id`` and order-timeout recovery (§17.1).

LIVE create-order responses are resolved through ``get_order`` polling when the
gateway supports it, then persisted/registered for reconciliation.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal

from packages.config.settings import AppConfig
from packages.core.enums import EntryMode, OrderStatus, OrderType, Side, TimeInForce
from packages.core.errors import OrderTimeoutError
from packages.core.models import (
    ExchangeOrder,
    ExchangeOrderResult,
    Order,
    OrderRequest,
    SymbolMeta,
)
from packages.exchange import ExchangeGateway
from packages.execution.order_policy import (
    aggressive_limit_price,
    assert_live_new_entry_allowed,
    entry_order_type,
)
from packages.entry.entry_timing_engine import EntryDecision  # noqa: F401 (typing)
from packages.universe import round_qty_down

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrderOutcome:
    status: str  # FILLED | PARTIAL | NO_FILL | REJECTED
    filled_qty: Decimal
    avg_price: Decimal | None
    order_id: str | None
    client_order_id: str | None
    reason: str = ""

    @property
    def is_filled(self) -> bool:
        return self.status in ("FILLED", "PARTIAL") and self.filled_qty > 0


def _opposite(side: Side) -> Side:
    return Side.SELL if side == Side.BUY else Side.BUY


class OrderManager:
    def __init__(
        self,
        gateway: ExchangeGateway,
        config: AppConfig,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        poll_interval_sec: float = 0.25,
        trade_logger=None,
        order_sink: Callable[[Order], None] | None = None,
        pending_order_sink: Callable[[str | None, str], None] | None = None,
        pending_order_clear_sink: Callable[[str | None], None] | None = None,
    ) -> None:
        self._gw = gateway
        self.cfg = config
        self._sleep = sleep
        self._clock = clock
        self._poll_interval_sec = poll_interval_sec
        self._logger = trade_logger
        self._order_sink = order_sink
        self._pending_order_sink = pending_order_sink
        self._pending_order_clear_sink = pending_order_clear_sink
        self._symbol_meta: dict[str, SymbolMeta] | None = None

    # ------------------------------------------------------------------ #
    @staticmethod
    def _cid(prefix: str = "qb") -> str:
        return f"{prefix}-{uuid.uuid4().hex[:20]}"

    def _passive_limit_price(
        self, side: Side, best_bid: Decimal, best_ask: Decimal
    ) -> Decimal:
        return best_bid if side == Side.BUY else best_ask

    # ------------------------------------------------------------------ #
    # entry
    # ------------------------------------------------------------------ #
    async def place_entry(
        self,
        *,
        symbol: str,
        side: Side,
        qty: Decimal,
        entry_mode,
        best_bid: Decimal,
        best_ask: Decimal,
        limit_price: Decimal | None = None,
    ) -> OrderOutcome:
        order_type = entry_order_type(entry_mode, self.cfg.orders)
        assert_live_new_entry_allowed(order_type, reduce_only=False, config=self.cfg.orders)
        if order_type == OrderType.AGGRESSIVE_LIMIT:
            return await self._place_aggressive(
                symbol, side, qty, best_bid, best_ask, entry_mode
            )
        price = limit_price or self._passive_limit_price(side, best_bid, best_ask)
        return await self._place_limit(symbol, side, qty, price, entry_mode)

    async def _place_aggressive(
        self,
        symbol: str,
        side: Side,
        qty: Decimal,
        best_bid: Decimal,
        best_ask: Decimal,
        entry_mode: EntryMode,
    ) -> OrderOutcome:
        price = aggressive_limit_price(
            side, best_ask, best_bid, Decimal(str(self.cfg.orders.max_slippage_percent))
        )
        cid = self._cid()
        res = await self._place(
            OrderRequest(
                symbol=symbol, side=side, order_type=OrderType.AGGRESSIVE_LIMIT,
                qty=qty, price=price, time_in_force=TimeInForce.IOC, client_order_id=cid,
            ),
            entry_mode=entry_mode,
        )
        filled = res.filled_qty
        if filled <= 0:
            return OrderOutcome("NO_FILL", Decimal(0), None, res.order_id, cid, "IOC_NO_FILL")

        keep_ratio = Decimal(str(self.cfg.orders.partial_fill_min_ratio_to_keep))
        ratio = filled / qty
        if ratio >= keep_ratio:
            if filled < qty:
                await self._safe_cancel(symbol, res.order_id, cid)
            status = "FILLED" if filled >= qty else "PARTIAL"
            return OrderOutcome(status, filled, res.avg_fill_price, res.order_id, cid)

        # Too small (impl doc §12.4): cancel remainder, flatten the small fill.
        await self._safe_cancel(symbol, res.order_id, cid)
        await self.place_exit(symbol=symbol, side=_opposite(side), qty=filled)
        return OrderOutcome(
            "REJECTED", Decimal(0), None, res.order_id, cid, "PARTIAL_FILL_TOO_SMALL"
        )

    async def _place_limit(
        self, symbol: str, side: Side, qty: Decimal, price: Decimal, entry_mode
    ) -> OrderOutcome:
        tries = self.cfg.orders.limit_reorder_attempts + 1
        for _ in range(tries):
            cid = self._cid()
            request = OrderRequest(
                symbol=symbol, side=side, order_type=OrderType.LIMIT,
                qty=qty, price=price, time_in_force=TimeInForce.GTC,
                client_order_id=cid,
            )
            res = await self._place(
                request,
                entry_mode=entry_mode,
                limit_ttl_sec=self._limit_ttl_sec(entry_mode),
            )
            filled = res.filled_qty
            if filled <= 0:
                await self._safe_cancel(symbol, res.order_id, cid)
                await self._record_order(
                    request,
                    res.model_copy(update={"status": OrderStatus.CANCELLED}),
                    entry_mode,
                )
                continue  # 0% within TTL -> cancel and maybe reorder
            if filled < qty:
                await self._safe_cancel(symbol, res.order_id, cid)
                await self._record_order(
                    request,
                    res.model_copy(update={"status": OrderStatus.CANCELLED}),
                    entry_mode,
                )
                return OrderOutcome("PARTIAL", filled, res.avg_fill_price, res.order_id, cid)
            return OrderOutcome("FILLED", filled, res.avg_fill_price, res.order_id, cid)
        # Scout/Retest never convert to MARKET (impl doc §12.3).
        return OrderOutcome("NO_FILL", Decimal(0), None, None, None, "LIMIT_UNFILLED")

    # ------------------------------------------------------------------ #
    # exit
    # ------------------------------------------------------------------ #
    async def place_exit(
        self,
        *,
        symbol: str,
        side: Side,
        qty: Decimal,
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
    ) -> OrderOutcome:
        """Reduce-only exit (impl doc §12.2). MARKET is allowed for reduce-only."""
        cid = self._cid("exit")
        tif = TimeInForce.IOC if order_type == OrderType.AGGRESSIVE_LIMIT else None
        res = await self._place(
            OrderRequest(
                symbol=symbol, side=side, order_type=order_type, qty=qty,
                price=price, reduce_only=True, time_in_force=tif, client_order_id=cid,
            )
        )
        filled = res.filled_qty
        status = (
            "FILLED"
            if res.status == OrderStatus.FILLED or filled >= qty
            else ("PARTIAL" if filled > 0 else "NO_FILL")
        )
        return OrderOutcome(status, filled, res.avg_fill_price, res.order_id, cid)

    async def place_partial_exit(
        self,
        *,
        symbol: str,
        side: Side,
        qty: Decimal,
        limit_price: Decimal | None,
        best_bid: Decimal,
        best_ask: Decimal,
    ) -> OrderOutcome:
        """Partial take-profit: reduce-only LIMIT first, MARKET fallback (impl doc §12.2)."""
        if limit_price is not None:
            cid = self._cid("ptp")
            res = await self._place(
                OrderRequest(
                    symbol=symbol, side=side, order_type=OrderType.LIMIT, qty=qty,
                    price=limit_price, reduce_only=True,
                    time_in_force=TimeInForce.GTC, client_order_id=cid,
                )
            )
            if res.status == OrderStatus.FILLED or res.filled_qty >= qty:
                return OrderOutcome("FILLED", res.filled_qty, res.avg_fill_price, res.order_id, cid)
            await self._safe_cancel(symbol, res.order_id, cid)
            remainder = qty - res.filled_qty
            if remainder > 0:
                mkt = await self.place_exit(symbol=symbol, side=side, qty=remainder)
                total = res.filled_qty + mkt.filled_qty
                status = "FILLED" if total >= qty else ("PARTIAL" if total > 0 else "NO_FILL")
                return OrderOutcome(status, total, mkt.avg_price or res.avg_fill_price, res.order_id, cid)
        # no limit price (or limit fully unfilled) -> reduce-only MARKET
        return await self.place_exit(symbol=symbol, side=side, qty=qty)

    # ------------------------------------------------------------------ #
    # order timeout recovery (impl doc §17.1)
    # ------------------------------------------------------------------ #
    async def _place(
        self,
        request: OrderRequest,
        entry_mode: EntryMode | None = None,
        *,
        limit_ttl_sec: int | None = None,
    ) -> ExchangeOrderResult:
        request = await self._normalize_request_qty(request)
        if request.qty <= 0:
            return ExchangeOrderResult(
                symbol=request.symbol,
                order_id="",
                client_order_id=request.client_order_id,
                status=OrderStatus.REJECTED,
                filled_qty=Decimal(0),
            )
        self._reserve_order(request)
        try:
            placed = await self._gw.place_order(request)
        except OrderTimeoutError:
            recovered = await self.recover_order(request.symbol, request.client_order_id)
            if recovered is not None:
                result = ExchangeOrderResult(
                    symbol=request.symbol,
                    order_id=recovered.order_id,
                    client_order_id=recovered.client_order_id,
                    status=recovered.status,
                    filled_qty=recovered.cum_exec_qty,
                    avg_fill_price=recovered.avg_price,
                )
                await self._record_order(request, result, entry_mode)
                self._clear_order_reservation(request.client_order_id)
                return result
            # Not found: retry once with a fresh id (caller handled idempotency).
            self._clear_order_reservation(request.client_order_id)
            retry = request.model_copy(update={"client_order_id": self._cid("retry")})
            self._reserve_order(retry)
            placed = await self._gw.place_order(retry)
            request = retry
        except Exception:
            self._clear_order_reservation(request.client_order_id)
            raise
        resolved = await self._resolve(request, placed, limit_ttl_sec=limit_ttl_sec)
        await self._record_order(request, resolved, entry_mode)
        self._clear_order_reservation(request.client_order_id)
        return resolved

    def _reserve_order(self, request: OrderRequest) -> None:
        if self._pending_order_sink is not None:
            self._pending_order_sink(request.client_order_id, request.symbol)

    def _clear_order_reservation(self, client_order_id: str | None) -> None:
        if self._pending_order_clear_sink is not None:
            self._pending_order_clear_sink(client_order_id)

    async def _resolve(
        self,
        request: OrderRequest,
        placed: ExchangeOrderResult,
        *,
        limit_ttl_sec: int | None = None,
    ) -> ExchangeOrderResult:
        """Resolve fill state after create-order.

        Test gateways already return a final snapshot. Live Bybit create-order
        responses usually do not, so if the gateway exposes ``get_order`` we poll
        until IOC has settled or a LIMIT TTL expires.
        """
        if placed.filled_qty > 0 or placed.status in (
            OrderStatus.FILLED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        ):
            return placed

        get_order = getattr(self._gw, "get_order", None)
        if get_order is None:
            return placed

        ttl = (
            0.0
            if request.time_in_force == TimeInForce.IOC
            else float(
                limit_ttl_sec
                if limit_ttl_sec is not None
                else self.cfg.orders.limit_order_ttl_sec
            )
        )
        deadline = self._clock() + ttl
        last = placed

        while True:
            order = await get_order(
                request.symbol, placed.order_id, placed.client_order_id
            )
            if order is None:
                return last
            last = ExchangeOrderResult(
                symbol=request.symbol,
                order_id=order.order_id,
                client_order_id=order.client_order_id,
                status=order.status,
                filled_qty=order.cum_exec_qty,
                avg_fill_price=order.avg_price,
            )
            if order.status in (
                OrderStatus.FILLED,
                OrderStatus.CANCELLED,
                OrderStatus.REJECTED,
                OrderStatus.EXPIRED,
            ):
                return last
            if (
                order.status == OrderStatus.PARTIALLY_FILLED
                and request.time_in_force == TimeInForce.IOC
            ):
                return last
            if request.time_in_force == TimeInForce.IOC or self._clock() >= deadline:
                return last
            await self._sleep(self._poll_interval_sec)

    async def recover_order(
        self, symbol: str, client_order_id: str | None
    ) -> ExchangeOrder | None:
        if client_order_id is None:
            return None
        for order in await self._gw.get_open_orders(symbol):
            if order.client_order_id == client_order_id:
                return order
        return None

    async def _safe_cancel(
        self, symbol: str, order_id: str | None, client_order_id: str | None
    ) -> None:
        try:
            await self._gw.cancel_order(symbol, order_id, client_order_id)
        except Exception:  # noqa: BLE001 - best effort
            logger.debug("cancel failed for %s/%s", order_id, client_order_id)

    async def _record_order(
        self,
        request: OrderRequest,
        result: ExchangeOrderResult,
        entry_mode: EntryMode | None,
        *,
        persist: bool = True,
    ) -> None:
        order = Order(
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            qty=request.qty,
            price=request.price,
            client_order_id=result.client_order_id or request.client_order_id,
            order_id=result.order_id,
            status=result.status,
            filled_qty=result.filled_qty,
            avg_fill_price=result.avg_fill_price,
            reduce_only=request.reduce_only,
            entry_mode=entry_mode,
        )
        if self._order_sink is not None:
            self._order_sink(order)
        if persist and self._logger is not None:
            await self._logger.log_order(order, mode="LIVE")

    def _limit_ttl_sec(self, entry_mode: EntryMode | None) -> int:
        if entry_mode == EntryMode.PRE_BREAKOUT_SCOUT:
            return self.cfg.orders.scout_limit_order_ttl_sec
        if entry_mode == EntryMode.RETEST_CONFIRM:
            return self.cfg.orders.retest_limit_order_ttl_sec
        return self.cfg.orders.limit_order_ttl_sec

    async def _normalize_request_qty(self, request: OrderRequest) -> OrderRequest:
        meta = await self._meta_for(request.symbol)
        if meta is None:
            return request
        qty = round_qty_down(request.qty, meta.qty_step)
        if qty == request.qty:
            return request
        logger.info(
            "rounded order qty for %s from %s to %s using step %s",
            request.symbol,
            request.qty,
            qty,
            meta.qty_step,
        )
        return request.model_copy(update={"qty": qty})

    async def _meta_for(self, symbol: str) -> SymbolMeta | None:
        if self._symbol_meta is None:
            try:
                instruments = await self._gw.load_instruments()
            except Exception:  # noqa: BLE001 - final exchange validation remains
                logger.debug("instrument metadata load failed")
                self._symbol_meta = {}
            else:
                self._symbol_meta = {m.symbol: m for m in instruments}
        return self._symbol_meta.get(symbol)
