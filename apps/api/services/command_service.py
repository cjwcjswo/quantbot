"""Command dispatch: persist command_log PENDING, then publish (backend doc §20).

DB write must succeed before publishing (§21.2): a command with no audit log is
never sent to the bot. Redis publish failure surfaces as 503.
"""

from __future__ import annotations

from typing import Any

from apps.api import errors
from apps.api.repositories import command_repository
from packages.messaging import Command, CommandType


async def dispatch(
    *, session_factory: Any, command_queue: Any, type: CommandType, payload: dict
) -> dict:
    cmd = Command(type=type, payload=payload)
    try:
        await command_repository.write_pending(
            session_factory, command_id=cmd.id, type=type.value, payload=payload)
    except Exception as exc:  # noqa: BLE001
        raise errors.database_error(
            "Command log write failed; command not published.",
            detail=str(exc),
        )
    try:
        await command_queue.publish(cmd)
    except Exception as exc:  # noqa: BLE001
        raise errors.queue_unavailable(detail=str(exc))
    return {"command_id": cmd.id, "status": "PENDING"}
