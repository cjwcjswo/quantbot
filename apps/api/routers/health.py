"""Health router (backend doc §9.1)."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from apps.api.dependencies import get_redis, get_session_factory
from apps.api.responses import ok

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    redis: Any = Depends(get_redis),
    session_factory: Any = Depends(get_session_factory),
) -> dict:
    postgres = "UP"
    try:
        async with session_factory() as session:
            await session.execute(select(1))
    except Exception:  # noqa: BLE001
        postgres = "DOWN"

    redis_status = "UP"
    try:
        await redis.ping()
    except Exception:  # noqa: BLE001
        redis_status = "DOWN"

    status = "OK" if postgres == "UP" and redis_status == "UP" else "DEGRADED"
    return ok({
        "status": status,
        "api": "UP",
        "postgres": postgres,
        "redis": redis_status,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
