"""FastAPI dependency providers (read from app.state populated in lifespan)."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from apps.api import errors
from apps.api.config import ApiSettings


def get_config(request: Request) -> Any:
    return request.app.state.config


def get_api_settings(request: Request) -> ApiSettings:
    return request.app.state.api_settings


def get_session_factory(request: Request) -> Any:
    return request.app.state.session_factory


def get_redis(request: Request) -> Any:
    return request.app.state.redis


def get_command_queue(request: Request) -> Any:
    return request.app.state.command_queue


def get_trade_logger(request: Request) -> Any:
    return request.app.state.trade_logger


def get_ws_hub(request: Request) -> Any:
    return request.app.state.ws_hub


def get_stream(request: Request) -> Any:
    return request.app.state.stream


async def require_auth(request: Request) -> None:
    """Enforce Bearer token on protected routes when auth is enabled (§7)."""
    settings: ApiSettings = request.app.state.api_settings
    if not settings.api_auth_enabled:
        return
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.startswith("Bearer ") else ""
    if token != settings.api_token_dev:
        raise errors.unauthorized()
