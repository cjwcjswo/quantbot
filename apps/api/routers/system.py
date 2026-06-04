"""System storage router (backend doc §25.10)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from apps.api.dependencies import get_session_factory
from apps.api.responses import ok
from apps.api.services import storage_service

router = APIRouter(tags=["system"])


@router.get("/system/storage")
async def system_storage(
    session_factory: Any = Depends(get_session_factory),
) -> dict:
    return ok(await storage_service.storage(session_factory))
