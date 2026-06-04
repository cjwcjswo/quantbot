"""Event bus: publishes BotEvents to Redis and an optional persistence sink.

Publishes to a Redis pub/sub channel (``events:bot``) for the dashboard and,
when configured, calls an async ``sink`` (e.g. TradeLogger) for durable storage.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from packages.core.events import BotEvent
from packages.messaging import state_keys

EventSink = Callable[[BotEvent], Awaitable[None]]


class EventBus:
    def __init__(
        self,
        redis: Any | None = None,
        channel: str = state_keys.EVENTS_BOT,
        sink: EventSink | None = None,
    ) -> None:
        self._redis = redis
        self._channel = channel
        self._sink = sink

    async def publish(self, event: BotEvent) -> None:
        if self._redis is not None:
            await self._redis.publish(self._channel, event.model_dump_json())
        if self._sink is not None:
            await self._sink(event)
