"""Tests for the single-instance runtime lock (arch doc §3.3)."""

import fakeredis.aioredis

from packages.messaging import RuntimeLock


async def test_second_instance_cannot_acquire(redis_server):
    r1 = fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)
    r2 = fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)
    lock1 = RuntimeLock(r1, ttl_sec=30)
    lock2 = RuntimeLock(r2, ttl_sec=30)

    assert await lock1.acquire() is True
    assert await lock2.acquire() is False
    assert lock1.held and not lock2.held


async def test_release_allows_reacquire(redis_server):
    r1 = fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)
    r2 = fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)
    lock1 = RuntimeLock(r1)
    lock2 = RuntimeLock(r2)

    await lock1.acquire()
    await lock1.release()
    assert await lock2.acquire() is True


async def test_refresh_only_when_owned(redis):
    lock = RuntimeLock(redis, ttl_sec=30)
    assert await lock.refresh() is False  # not held yet
    await lock.acquire()
    assert await lock.refresh() is True


async def test_release_does_not_clobber_other_owner(redis_server):
    r1 = fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)
    r2 = fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True)
    lock1 = RuntimeLock(r1)
    lock2 = RuntimeLock(r2)
    await lock1.acquire()
    # lock2 never owned it; releasing must not remove lock1's key.
    await lock2.release()
    assert await lock2.acquire() is False
