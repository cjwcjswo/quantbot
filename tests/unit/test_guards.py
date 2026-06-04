"""Tests for rate limiter, backoff, and clock-sync guard."""

import asyncio
import time

import pytest

from packages.guards import ClockSyncGuard, RateLimiter, with_backoff


async def test_rate_limiter_throttles():
    limiter = RateLimiter(rate=5)
    start = time.monotonic()
    # 5 initial tokens (burst) + 2 more must wait ~ 2/5 sec.
    for _ in range(7):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.3


async def test_with_backoff_retries_then_succeeds():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    result = await with_backoff(flaky, retries=5, base_sec=0.001, max_sec=0.01)
    assert result == "ok"
    assert calls["n"] == 3


async def test_with_backoff_exhausts():
    async def always_fail():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        await with_backoff(always_fail, retries=2, base_sec=0.001, max_sec=0.01)


def test_clock_sync_within_tolerance():
    guard = ClockSyncGuard(max_time_drift_ms=500, block_trading_if_drift_ms_above=1000)
    guard.update(server_time_ms=1_000_000, local_time_ms=1_000_200)
    assert guard.drift_ms == 200
    assert guard.is_within_tolerance()


def test_clock_sync_blocks_on_large_drift():
    guard = ClockSyncGuard(max_time_drift_ms=500, block_trading_if_drift_ms_above=1000)
    guard.update(server_time_ms=1_000_000, local_time_ms=1_002_000)
    assert guard.drift_ms == 2000
    assert not guard.is_within_tolerance()
