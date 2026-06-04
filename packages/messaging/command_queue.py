"""Bot command queue over a Redis list (arch doc §5.2, §8 commands:bot).

Backend pushes commands with :meth:`CommandQueue.publish`; the Bot Engine's
CommandConsumer pulls them with :meth:`CommandQueue.consume` (blocking BRPOP).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from packages.messaging import state_keys


class CommandType(StrEnum):
    """Commands the Backend API may issue (arch doc §5.2)."""

    START_BOT = "START_BOT"
    STOP_BOT = "STOP_BOT"
    PAUSE_TRADING = "PAUSE_TRADING"
    RESUME_TRADING = "RESUME_TRADING"
    RELOAD_CONFIG = "RELOAD_CONFIG"
    CLOSE_POSITION = "CLOSE_POSITION"
    CANCEL_ORDER = "CANCEL_ORDER"
    SYNC_NOW = "SYNC_NOW"


class Command(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: CommandType
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CommandQueue:
    def __init__(self, redis: Any, key: str = state_keys.COMMANDS_BOT) -> None:
        self._redis = redis
        self._key = key

    async def publish(self, command: Command) -> None:
        """Enqueue a command (Backend side; also used in tests)."""
        await self._redis.lpush(self._key, command.model_dump_json())

    async def consume(self, timeout: float = 1.0) -> Command | None:
        """Block up to ``timeout`` seconds for the next command (FIFO)."""
        result = await self._redis.brpop([self._key], timeout=timeout)
        if result is None:
            return None
        # redis-py returns (key, value); decode_responses gives str.
        _key, raw = result
        return Command.model_validate_json(raw)
