"""FastAPI app factory for the QuantBot Backend API."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.config import ApiSettings
from apps.api.errors import register_exception_handlers
from apps.api.lifespan import attach_runtime, lifespan
from apps.api.routers import (
    bot,
    events,
    health,
    logs,
    orders,
    pnl,
    positions,
    strategy_config,
    system,
    trades,
    websocket,
)


def create_app(
    *,
    session_factory: Any | None = None,
    redis: Any | None = None,
    config: Any | None = None,
    api_settings: ApiSettings | None = None,
    start_stream: bool = True,
) -> FastAPI:
    """Build the app. Tests inject session_factory/redis/config and usually
    pass start_stream=False so the DashboardStream background tasks stay off."""
    settings = api_settings or ApiSettings()
    app = FastAPI(title="QuantBot API", version="1.1.0", lifespan=lifespan)

    # values consumed by lifespan
    app.state.injected_session_factory = session_factory
    app.state.injected_redis = redis
    app.state.injected_config = config
    app.state.injected_api_settings = api_settings
    app.state.injected_start_stream = start_stream

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    # When tests inject session_factory + redis, wire runtime state eagerly so the
    # app works under httpx ASGITransport (which does not run the lifespan).
    if session_factory is not None and redis is not None:
        from packages.config import load_app_config

        attach_runtime(
            app,
            config=config or load_app_config("config/quantbot.yaml"),
            api_settings=settings,
            session_factory=session_factory,
            redis=redis,
        )

    for module in (
        health, bot, positions, orders, trades, pnl,
        strategy_config, events, logs, system, websocket,
    ):
        app.include_router(module.router)

    return app


app = create_app()
