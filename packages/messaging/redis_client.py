"""Redis async client factory.

Production uses redis-py asyncio; tests pass a ``fakeredis.aioredis`` client to
the queue / bus / lock classes directly, so this factory stays trivial.
"""

from __future__ import annotations

from typing import Any


def create_redis(url: str) -> Any:
    """Create a redis.asyncio client with string decoding enabled."""
    import redis.asyncio as redis

    return redis.from_url(url, decode_responses=True)
