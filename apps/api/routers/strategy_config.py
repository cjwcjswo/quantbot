"""Strategy config router (backend doc §15)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from apps.api.dependencies import (
    get_command_queue,
    get_config,
    get_redis,
    get_session_factory,
    require_auth,
)
from apps.api.responses import ok
from apps.api.schemas.strategy_config import ConfigPatchReq
from apps.api.services import strategy_config_service

router = APIRouter(tags=["strategy"])


@router.get("/strategy/config")
async def get_strategy_config(
    redis: Any = Depends(get_redis),
    session_factory: Any = Depends(get_session_factory),
    config: Any = Depends(get_config),
) -> dict:
    return ok(await strategy_config_service.get_config(session_factory, redis, config))


@router.put("/strategy/config", dependencies=[Depends(require_auth)])
async def put_config(
    body: ConfigPatchReq,
    redis: Any = Depends(get_redis),
    session_factory: Any = Depends(get_session_factory),
    command_queue: Any = Depends(get_command_queue),
) -> dict:
    result = await strategy_config_service.patch_config(
        session_factory, redis, command_queue,
        config_version=body.config_version, patch=body.patch, reason=body.reason)
    return ok(result)
