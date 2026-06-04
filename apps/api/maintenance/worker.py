"""MaintenanceWorker: schedules the §25 jobs; can be split into its own process."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

from apps.api.maintenance import jobs
from apps.api.maintenance.retention_policy import RetentionPolicy, load_retention_policy
from apps.api.maintenance.scheduler import KstScheduler

logger = logging.getLogger(__name__)


class MaintenanceWorker:
    def __init__(
        self, session_factory: async_sessionmaker, policy: RetentionPolicy | None = None
    ) -> None:
        self._sf = session_factory
        self._policy = policy or load_retention_policy()
        self._scheduler = KstScheduler()
        self._db_ok = True

    def start(self) -> None:
        self._scheduler.start()
        self._scheduler.run_daily_at(0, 5, self._daily_summary)
        self._scheduler.run_daily_at(0, 20, self._archive)
        self._scheduler.run_daily_at(0, 40, self._cleanup)
        self._scheduler.run_every(60, self._health_check)

    async def stop(self) -> None:
        await self._scheduler.stop()

    # job wrappers honoring the DB-health gate (§25.11) --------------------- #
    async def _health_check(self) -> None:
        self._db_ok = await jobs.database_health_check(self._sf)

    async def _daily_summary(self) -> None:
        if not self._db_ok:
            return
        await jobs.daily_summary(self._sf, self._policy)

    async def _archive(self) -> None:
        if not self._db_ok:
            logger.warning("skipping archive: db not healthy")
            return
        await jobs.archive_job(self._sf, self._policy)

    async def _cleanup(self) -> None:
        if not self._db_ok:
            logger.warning("skipping cleanup: db not healthy")
            return
        await jobs.retention_cleanup(self._sf, self._policy)


async def _amain() -> None:
    import asyncio

    from packages.config.settings import load_secrets
    from packages.storage import create_engine, init_models, make_session_factory

    logging.basicConfig(level=logging.INFO)
    secrets = load_secrets()
    engine = create_engine(secrets.database_url)
    await init_models(engine)
    worker = MaintenanceWorker(make_session_factory(engine))
    worker.start()
    logger.info("maintenance worker started")
    try:
        await asyncio.Event().wait()
    finally:
        await worker.stop()
        await engine.dispose()


def main() -> None:
    import asyncio

    asyncio.run(_amain())


if __name__ == "__main__":
    main()
