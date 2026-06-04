"""Client-side API rate limiting and backoff (impl doc §7 api_rate_limit).

``RateLimiter`` is a simple async token bucket: at most ``rate`` permits are
granted per second. ``with_backoff`` retries a coroutine with exponential
backoff bounded by ``backoff_max_sec``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from packages.core.errors import RateLimitError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RateLimiter:
    """Token-bucket limiter allowing ``rate`` acquisitions per second."""

    def __init__(self, rate: int, capacity: int | None = None) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        self._rate = float(rate)
        self._capacity = float(capacity if capacity is not None else rate)
        self._tokens = self._capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._updated
        self._updated = now
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)

    async def acquire(self) -> None:
        """Block until a permit is available."""
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                deficit = 1 - self._tokens
                await asyncio.sleep(deficit / self._rate)

    async def __aenter__(self) -> "RateLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


async def with_backoff(
    func: Callable[[], Awaitable[T]],
    *,
    retries: int = 3,
    base_sec: float = 1.0,
    max_sec: float = 30.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
) -> T:
    """Call ``func`` with exponential backoff on failure.

    Raises the last exception (wrapped in ``RateLimitError`` if it was the final
    attempt and no more retries remain) after exhausting ``retries``.
    """
    attempt = 0
    while True:
        try:
            return await func()
        except retry_on as exc:
            attempt += 1
            if attempt > retries:
                logger.error("with_backoff exhausted after %d attempts", attempt)
                raise
            delay = min(max_sec, base_sec * (2 ** (attempt - 1)))
            logger.warning(
                "with_backoff attempt %d failed (%s); retrying in %.1fs",
                attempt,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
