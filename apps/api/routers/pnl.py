"""PnL router (backend doc §14)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from apps.api.dependencies import get_redis, get_session_factory
from apps.api.responses import ok
from apps.api.services import pnl_service

router = APIRouter(tags=["pnl"])


@router.get("/pnl/summary")
async def pnl_summary(
    redis: Any = Depends(get_redis),
    session_factory: Any = Depends(get_session_factory),
) -> dict:
    return ok(await pnl_service.summary(redis, session_factory))


@router.get("/pnl/daily")
async def pnl_daily(
    limit: int = Query(90, ge=1, le=400),
    session_factory: Any = Depends(get_session_factory),
) -> dict:
    return ok({"daily": await pnl_service.daily(session_factory, limit=limit)})
