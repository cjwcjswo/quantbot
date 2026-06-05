"""Bot status + command routers (backend doc §9.2, §10, §21)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from apps.api import errors
from apps.api.dependencies import (
    get_config,
    get_api_settings,
    get_command_queue,
    get_redis,
    get_session_factory,
    require_auth,
)
from apps.api.repositories import command_repository
from apps.api.responses import ok
from apps.api.schemas.bot import PauseReq, ResumeReq, StartReq, StopReq
from apps.api.services import bot_status_service, command_service
from packages.core.enums import BotMode
from packages.messaging import CommandType, state_keys

router = APIRouter(tags=["bot"])

# commands allowed even when the bot heartbeat is stale (§21.3)
_ALLOWED_WHEN_STALE = {CommandType.START_BOT, CommandType.STOP_BOT, CommandType.SYNC_NOW}


async def _read_state(redis: Any, settings: Any) -> tuple[str | None, bool]:
    try:
        return await bot_status_service.raw_state(redis, settings.heartbeat_alive_sec)
    except Exception as exc:  # noqa: BLE001
        raise errors.redis_error(detail=str(exc))


def _guard_alive(cmd: CommandType, is_alive: bool) -> None:
    if not is_alive and cmd not in _ALLOWED_WHEN_STALE:
        raise errors.bot_not_running(
            "Bot heartbeat is stale; only START/STOP/SYNC are allowed.")


@router.get("/bot/status")
async def bot_status(
    redis: Any = Depends(get_redis),
    session_factory: Any = Depends(get_session_factory),
    settings: Any = Depends(get_api_settings),
) -> dict:
    return ok(await bot_status_service.get_status(redis, session_factory, settings))


@router.post("/bot/start", dependencies=[Depends(require_auth)])
async def bot_start(
    body: StartReq,
    config: Any = Depends(get_config),
    redis: Any = Depends(get_redis),
    settings: Any = Depends(get_api_settings),
    session_factory: Any = Depends(get_session_factory),
    command_queue: Any = Depends(get_command_queue),
) -> dict:
    state, is_alive = await _read_state(redis, settings)
    if state == "RUNNING":
        raise errors.conflict("Bot is already running.")
    if state not in (None, "STANDBY", "PAUSED", "STOPPED"):
        raise errors.command_rejected(f"Cannot start from state {state}.")
    mode = await redis.get(state_keys.BOT_MODE)
    if mode is None:
        mode = config.bot.mode.value
    if mode == BotMode.LIVE.value:
        if not body.live_confirm:
            raise errors.ApiError(
                errors.ErrorCode.VALIDATION_ERROR,
                "LIVE start requires live_confirm=true.")
        if not is_alive:
            raise errors.bot_not_running("Bot heartbeat is stale; cannot start LIVE.")
    result = await command_service.dispatch(
        session_factory=session_factory, command_queue=command_queue,
        type=CommandType.START_BOT, payload={})
    return ok(result)


@router.post("/bot/stop", dependencies=[Depends(require_auth)])
async def bot_stop(
    body: StopReq,
    redis: Any = Depends(get_redis),
    settings: Any = Depends(get_api_settings),
    session_factory: Any = Depends(get_session_factory),
    command_queue: Any = Depends(get_command_queue),
) -> dict:
    await _read_state(redis, settings)
    result = await command_service.dispatch(
        session_factory=session_factory, command_queue=command_queue,
        type=CommandType.STOP_BOT,
        payload={"close_positions": body.close_positions,
                 "cancel_open_orders": body.cancel_open_orders})
    return ok(result)


@router.post("/bot/pause", dependencies=[Depends(require_auth)])
async def bot_pause(
    body: PauseReq,
    redis: Any = Depends(get_redis),
    settings: Any = Depends(get_api_settings),
    session_factory: Any = Depends(get_session_factory),
    command_queue: Any = Depends(get_command_queue),
) -> dict:
    state, is_alive = await _read_state(redis, settings)
    _guard_alive(CommandType.PAUSE_TRADING, is_alive)
    if state != "RUNNING":
        raise errors.bot_not_running("Bot must be RUNNING to pause.")
    result = await command_service.dispatch(
        session_factory=session_factory, command_queue=command_queue,
        type=CommandType.PAUSE_TRADING, payload={"reason": body.reason})
    return ok(result)


@router.post("/bot/resume", dependencies=[Depends(require_auth)])
async def bot_resume(
    body: ResumeReq,
    redis: Any = Depends(get_redis),
    settings: Any = Depends(get_api_settings),
    session_factory: Any = Depends(get_session_factory),
    command_queue: Any = Depends(get_command_queue),
) -> dict:
    state, is_alive = await _read_state(redis, settings)
    _guard_alive(CommandType.RESUME_TRADING, is_alive)
    if state in ("RISK_LOCKED", "EMERGENCY_STOP"):
        raise errors.command_rejected(f"Cannot resume from state {state}.")
    if state != "PAUSED":
        raise errors.command_rejected("Bot must be PAUSED to resume.")
    result = await command_service.dispatch(
        session_factory=session_factory, command_queue=command_queue,
        type=CommandType.RESUME_TRADING, payload={"reason": body.reason})
    return ok(result)


@router.get("/commands/{command_id}")
async def command_status(
    command_id: str,
    session_factory: Any = Depends(get_session_factory),
) -> dict:
    row = await command_repository.get_status(session_factory, command_id)
    if row is None:
        raise errors.not_found(f"No command {command_id}.", command_id=command_id)
    return ok(row)


@router.post("/bot/sync", dependencies=[Depends(require_auth)])
async def bot_sync(
    redis: Any = Depends(get_redis),
    settings: Any = Depends(get_api_settings),
    session_factory: Any = Depends(get_session_factory),
    command_queue: Any = Depends(get_command_queue),
) -> dict:
    await _read_state(redis, settings)
    result = await command_service.dispatch(
        session_factory=session_factory, command_queue=command_queue,
        type=CommandType.SYNC_NOW, payload={})
    return ok(result)
