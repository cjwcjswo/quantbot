"""Daily log router (backend doc §25.8)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from apps.api import errors
from apps.api.dependencies import get_session_factory
from apps.api.responses import ok
from apps.api.services import log_service

router = APIRouter(tags=["logs"])


@router.get("/logs/daily")
async def daily_log(
    date: str = Query(...),
    mode: str | None = None,
    session_factory: Any = Depends(get_session_factory),
) -> dict:
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise errors.ApiError(
            errors.ErrorCode.VALIDATION_ERROR, f"Invalid date: {date} (YYYY-MM-DD)")
    return ok(await log_service.daily(session_factory, day=date, mode=mode))


@router.get("/logs/daily/calendar")
async def daily_calendar(
    year: int = Query(..., ge=2000, le=3000),
    month: int = Query(..., ge=1, le=12),
    mode: str | None = None,
    session_factory: Any = Depends(get_session_factory),
) -> dict:
    return ok(await log_service.calendar(
        session_factory, year=year, month=month, mode=mode))
