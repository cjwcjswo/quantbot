"""Events router (backend doc §16)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from apps.api.dependencies import get_session_factory
from apps.api.repositories import event_repository
from apps.api.responses import ok
from apps.api.util import parse_dt

router = APIRouter(tags=["events"])


@router.get("/events")
async def list_events(
    event_type: str | None = None,
    severity: str | None = None,
    symbol: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    session_factory: Any = Depends(get_session_factory),
) -> dict:
    rows = await event_repository.list_events(
        session_factory, event_type=event_type, severity=severity, symbol=symbol,
        frm=parse_dt(from_), to=parse_dt(to), limit=limit, offset=offset)
    return ok({"events": rows})
