"""Orders router (backend doc §12)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from apps.api import errors
from apps.api.dependencies import (
    get_command_queue,
    get_session_factory,
    require_auth,
)
from apps.api.repositories import order_repository
from apps.api.responses import ok
from apps.api.schemas.orders import CancelReq
from apps.api.services import command_service
from apps.api.util import parse_dt
from packages.messaging import CommandType

router = APIRouter(tags=["orders"])

_STATUSES = {"NEW", "PARTIALLY_FILLED", "FILLED", "CANCELED", "CANCELLED",
             "REJECTED", "EXPIRED", "FAILED", "UNKNOWN"}
_CANCELABLE_STATUSES = {"NEW", "PARTIALLY_FILLED", "UNKNOWN"}


@router.get("/orders")
async def list_orders(
    symbol: str | None = None,
    status: str | None = None,
    source: str | None = None,
    mode: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    session_factory: Any = Depends(get_session_factory),
) -> dict:
    if status is not None and status not in _STATUSES:
        raise errors.ApiError(
            errors.ErrorCode.VALIDATION_ERROR, f"Invalid status: {status}")
    rows = await order_repository.list_orders(
        session_factory, symbol=symbol, status=status, source=source, mode=mode,
        frm=parse_dt(from_), to=parse_dt(to), limit=limit, offset=offset)
    return ok({"orders": rows})


@router.post("/orders/{order_id}/cancel", dependencies=[Depends(require_auth)])
async def cancel_order(
    order_id: str,
    body: CancelReq,
    session_factory: Any = Depends(get_session_factory),
    command_queue: Any = Depends(get_command_queue),
) -> dict:
    order = await order_repository.get_by_order_id(session_factory, order_id)
    if order is None:
        raise errors.not_found(f"No order {order_id}.", order_id=order_id)
    if order.get("status") not in _CANCELABLE_STATUSES:
        raise errors.command_rejected(
            f"Order {order_id} is not cancelable from status {order.get('status')}.",
            order_id=order_id, status=order.get("status"))
    result = await command_service.dispatch(
        session_factory=session_factory, command_queue=command_queue,
        type=CommandType.CANCEL_ORDER,
        payload={"order_id": order_id, "symbol": order.get("symbol"),
                 "reason": body.reason})
    return ok(result)
