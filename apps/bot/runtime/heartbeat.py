"""Heartbeat: refreshes the runtime lock and publishes liveness to Redis.

Full realtime publishing (positions/pnl/protection) is StatePublisher in Phase 8;
this keeps the lock alive and the basic status/mode/heartbeat keys fresh.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from apps.bot.runtime.bot_state_machine import BotStateMachine
from packages.core.enums import BotMode
from packages.messaging import RuntimeLock, state_keys

logger = logging.getLogger(__name__)


class Heartbeat:
    def __init__(
        self,
        redis: Any | None,
        lock: RuntimeLock | None,
        state_machine: BotStateMachine,
        mode: BotMode,
    ) -> None:
        self._redis = redis
        self._lock = lock
        self._sm = state_machine
        self._mode = mode

    async def beat_once(self) -> None:
        if self._lock is not None:
            await self._lock.refresh()
        if self._redis is not None:
            now_ms = str(int(time.time() * 1000))
            await self._redis.set(state_keys.BOT_HEARTBEAT, now_ms)
            await self._redis.set(state_keys.BOT_STATUS, self._sm.state.value)
            await self._redis.set(state_keys.BOT_MODE, self._mode.value)
