"""Positions router (backend doc §11)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from apps.api import errors
from apps.api.dependencies import (
    get_api_settings,
    get_command_queue,
    get_redis,
    get_session_factory,
    require_auth,
)
from apps.api.responses import ok
from apps.api.schemas.positions import CloseReq
from apps.api.services import bot_status_service, command_service, position_service
from packages.messaging import CommandType

router = APIRouter(tags=["positions"])


@router.get("/positions")
async def list_positions(
    redis: Any = Depends(get_redis),
    session_factory: Any = Depends(get_session_factory),
) -> dict:
    return ok(await position_service.list_positions(redis, session_factory))


@router.get("/positions/{symbol}")
async def position_detail(
    symbol: str,
    session_factory: Any = Depends(get_session_factory),
) -> dict:
    data = await position_service.detail(session_factory, symbol)
    if data is None:
        raise errors.not_found(f"No position for {symbol}.", symbol=symbol)
    return ok(data)


@router.post("/positions/{symbol}/close", dependencies=[Depends(require_auth)])
async def close_position(
    symbol: str,
    body: CloseReq,
    redis: Any = Depends(get_redis),
    settings: Any = Depends(get_api_settings),
    session_factory: Any = Depends(get_session_factory),
    command_queue: Any = Depends(get_command_queue),
) -> dict:
    try:
        _, is_alive = await bot_status_service.raw_state(redis, settings.heartbeat_alive_sec)
    except Exception as exc:  # noqa: BLE001
        raise errors.redis_error(detail=str(exc))
    if not is_alive:
        raise errors.bot_not_running(
            "Closing positions is unsafe while the bot is inactive.")
    if not await position_service.exists(redis, session_factory, symbol):
        raise errors.not_found(f"No open position for {symbol}.", symbol=symbol)
    result = await command_service.dispatch(
        session_factory=session_factory, command_queue=command_queue,
        type=CommandType.CLOSE_POSITION,
        payload={"symbol": symbol, "close_percent": body.close_percent,
                 "reason": body.reason})
    return ok(result)
