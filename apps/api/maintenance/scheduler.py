"""KstScheduler: tiny asyncio wall-clock scheduler (backend doc §25.7).

Avoids a heavy dependency (APScheduler). Jobs are plain async callables; tests
invoke the job functions directly without the scheduler.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

JobFactory = Callable[[], Awaitable[None]]


def _seconds_until_kst(hour: int, minute: int, now: datetime | None = None) -> float:
    now = now or datetime.now(KST)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


class KstScheduler:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._running = False

    def run_daily_at(self, hour: int, minute: int, job: JobFactory) -> None:
        self._tasks.append(asyncio.create_task(self._daily_loop(hour, minute, job)))

    def run_every(self, minutes: float, job: JobFactory) -> None:
        self._tasks.append(asyncio.create_task(self._interval_loop(minutes, job)))

    def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks = []

    async def _daily_loop(self, hour: int, minute: int, job: JobFactory) -> None:
        self._running = True
        while self._running:
            try:
                await asyncio.sleep(_seconds_until_kst(hour, minute))
                if not self._running:
                    break
                await job()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("daily job error: %s", exc)

    async def _interval_loop(self, minutes: float, job: JobFactory) -> None:
        self._running = True
        while self._running:
            try:
                await asyncio.sleep(minutes * 60)
                if not self._running:
                    break
                await job()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("interval job error: %s", exc)
