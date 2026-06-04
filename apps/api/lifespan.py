"""Application lifespan + runtime wiring (shared by create_app and lifespan)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from apps.api.config import ApiSettings
from apps.api.maintenance import MaintenanceWorker, load_retention_policy
from apps.api.websocket import ConnectionManager, DashboardStream
from packages.config import load_app_config, load_secrets
from packages.observability import setup_logging
from packages.messaging import CommandQueue, create_redis
from packages.storage import (
    TradeLogger,
    create_engine,
    init_models,
    make_session_factory,
)

logger = logging.getLogger(__name__)


def attach_runtime(
    app: FastAPI, *, config: Any, api_settings: ApiSettings,
    session_factory: Any, redis: Any, engine: Any = None,
) -> None:
    """Populate app.state with the sync runtime objects (no I/O)."""
    st = app.state
    st.config = config
    st.api_settings = api_settings
    st.engine = engine
    st.session_factory = session_factory
    st.redis = redis
    st.command_queue = CommandQueue(redis)
    st.trade_logger = TradeLogger(session_factory)
    st.ws_hub = ConnectionManager()
    st.stream = DashboardStream(redis, st.ws_hub, api_settings)
    st.maintenance = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    st = app.state
    engine = None

    # File logging is wired here (not in create_app) so the test path, which uses
    # ASGITransport and never runs lifespan, does not write log files.
    setup_logging("api", capture_uvicorn=True)

    if getattr(st, "session_factory", None) is None:
        # production path: build engine + redis from secrets
        api_settings = getattr(st, "injected_api_settings", None) or ApiSettings()
        secrets = load_secrets()
        config = getattr(st, "injected_config", None) or load_app_config(
            secrets.quantbot_config)
        engine = create_engine(secrets.database_url)
        try:
            await init_models(engine)
        except Exception as exc:  # noqa: BLE001 - boot degraded if DB is down
            logger.warning("DB init failed (running degraded): %s", exc)
        session_factory = make_session_factory(engine)
        redis = getattr(st, "injected_redis", None) or create_redis(secrets.redis_url)
        attach_runtime(app, config=config, api_settings=api_settings,
                       session_factory=session_factory, redis=redis, engine=engine)
    else:
        engine = getattr(st, "engine", None)

    start_stream = getattr(st, "injected_start_stream", True)
    if start_stream:
        await st.stream.start()

    injected = getattr(st, "injected_session_factory", None) is not None
    if st.api_settings.api_run_maintenance and not injected:
        st.maintenance = MaintenanceWorker(st.session_factory, load_retention_policy())
        st.maintenance.start()

    logger.info("QuantBot API ready (env=%s)", st.api_settings.app_env)
    try:
        yield
    finally:
        if getattr(st, "stream", None) is not None:
            await st.stream.stop()
        if getattr(st, "maintenance", None) is not None:
            await st.maintenance.stop()
        if engine is not None:
            await engine.dispose()
