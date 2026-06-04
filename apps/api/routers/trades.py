"""Trades + fills router (backend doc §13, §25.9)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from apps.api import errors
from apps.api.dependencies import get_session_factory
from apps.api.repositories import fill_repository, trade_repository
from apps.api.responses import ok
from apps.api.util import parse_dt

router = APIRouter(tags=["trades"])


@router.get("/trades")
async def list_trades(
    symbol: str | None = None,
    strategy_id: str | None = None,
    entry_mode: str | None = None,
    mode: str | None = None,
    exit_reason: str | None = None,
    pnl: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    session_factory: Any = Depends(get_session_factory),
) -> dict:
    if pnl is not None and pnl not in ("positive", "negative"):
        raise errors.ApiError(errors.ErrorCode.VALIDATION_ERROR, f"Invalid pnl: {pnl}")
    rows = await trade_repository.list_trades(
        session_factory, symbol=symbol, strategy_id=strategy_id,
        entry_mode=entry_mode, mode=mode, exit_reason=exit_reason, pnl=pnl,
        frm=parse_dt(from_), to=parse_dt(to), limit=limit, offset=offset)
    return ok({"trades": rows})


@router.get("/fills")
async def list_fills(
    symbol: str | None = None,
    order_id: str | None = None,
    mode: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    session_factory: Any = Depends(get_session_factory),
) -> dict:
    rows = await fill_repository.list_fills(
        session_factory, symbol=symbol, order_id=order_id, mode=mode,
        frm=parse_dt(from_), to=parse_dt(to), limit=limit, offset=offset)
    return ok({"fills": rows})


@router.get("/trades/{trade_id}")
async def trade_detail(
    trade_id: str,
    session_factory: Any = Depends(get_session_factory),
) -> dict:
    data = await trade_repository.detail(session_factory, trade_id)
    if data is None:
        raise errors.not_found(f"No trade {trade_id}.", trade_id=trade_id)
    return ok(data)
