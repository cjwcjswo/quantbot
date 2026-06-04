"""Watch list router: scanner candidates + per-symbol entry preview (arch §6.11/§6.18)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from apps.api.dependencies import get_redis
from apps.api.responses import ok
from apps.api.services import watchlist_service

router = APIRouter(tags=["watchlist"])


@router.get("/watchlist")
async def get_watchlist(redis: Any = Depends(get_redis)) -> dict:
    return ok(await watchlist_service.get_watchlist(redis))
