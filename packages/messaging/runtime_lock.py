"""Single-instance runtime lock (arch doc §3.3).

The Bot Engine must not run twice. On startup it acquires ``lock:quantbot:live``
via ``SET key token NX EX ttl``; the heartbeat refreshes the TTL. A unique token
ensures only the owner can release, so a crashed instance's lock expires on its
own without a healthy instance clobbering someone else's lock.
"""

from __future__ import annotations

import uuid
from typing import Any

from packages.messaging import state_keys

# Lua: release only if we still own the lock.
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

# Lua: refresh TTL only if we still own the lock.
_REFRESH_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], ARGV[2])
else
    return 0
end
"""


class RuntimeLock:
    def __init__(
        self,
        redis: Any,
        key: str = state_keys.LOCK_LIVE,
        ttl_sec: int = 30,
    ) -> None:
        self._redis = redis
        self._key = key
        self._ttl_ms = ttl_sec * 1000
        self._token = uuid.uuid4().hex
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    async def acquire(self) -> bool:
        """Try to acquire the lock. Returns True on success."""
        ok = await self._redis.set(
            self._key, self._token, nx=True, px=self._ttl_ms
        )
        self._held = bool(ok)
        return self._held

    async def refresh(self) -> bool:
        """Extend the TTL if still owned (called by the heartbeat)."""
        if not self._held:
            return False
        result = await self._redis.eval(
            _REFRESH_LUA, 1, self._key, self._token, str(self._ttl_ms)
        )
        self._held = bool(result)
        return self._held

    async def release(self) -> None:
        if not self._held:
            return
        await self._redis.eval(_RELEASE_LUA, 1, self._key, self._token)
        self._held = False
