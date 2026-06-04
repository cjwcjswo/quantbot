"""Error codes, ApiError, and exception handlers (backend doc §8, §21)."""

from __future__ import annotations

from enum import StrEnum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from apps.api.responses import err


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    BOT_NOT_RUNNING = "BOT_NOT_RUNNING"
    BOT_COMMAND_REJECTED = "BOT_COMMAND_REJECTED"
    COMMAND_QUEUE_UNAVAILABLE = "COMMAND_QUEUE_UNAVAILABLE"
    DATABASE_ERROR = "DATABASE_ERROR"
    REDIS_ERROR = "REDIS_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


_HTTP_STATUS: dict[str, int] = {
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.BOT_NOT_RUNNING: 409,
    ErrorCode.BOT_COMMAND_REJECTED: 409,
    ErrorCode.COMMAND_QUEUE_UNAVAILABLE: 503,
    ErrorCode.DATABASE_ERROR: 503,
    ErrorCode.REDIS_ERROR: 503,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.CONFLICT: 409,
    ErrorCode.INTERNAL_ERROR: 500,
}


class ApiError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        http_status: int | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status or _HTTP_STATUS.get(code, 500)
        self.details = details or {}


# Convenience raisers -------------------------------------------------------- #
def not_found(message: str, **details) -> ApiError:
    return ApiError(ErrorCode.NOT_FOUND, message, details=details or None)


def conflict(message: str, **details) -> ApiError:
    return ApiError(ErrorCode.CONFLICT, message, details=details or None)


def bot_not_running(message: str = "Bot is not running.", **details) -> ApiError:
    return ApiError(ErrorCode.BOT_NOT_RUNNING, message, details=details or None)


def command_rejected(message: str, **details) -> ApiError:
    return ApiError(ErrorCode.BOT_COMMAND_REJECTED, message, details=details or None)


def database_error(message: str = "Database unavailable.", **details) -> ApiError:
    return ApiError(ErrorCode.DATABASE_ERROR, message, details=details or None)


def redis_error(message: str = "Redis unavailable.", **details) -> ApiError:
    return ApiError(ErrorCode.REDIS_ERROR, message, details=details or None)


def queue_unavailable(message: str = "Command queue unavailable.", **details) -> ApiError:
    return ApiError(ErrorCode.COMMAND_QUEUE_UNAVAILABLE, message, details=details or None)


def forbidden(message: str, **details) -> ApiError:
    return ApiError(ErrorCode.FORBIDDEN, message, details=details or None)


def unauthorized(message: str = "Unauthorized.") -> ApiError:
    return ApiError(ErrorCode.UNAUTHORIZED, message)


def register_exception_handlers(app: FastAPI) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    try:
        from redis.exceptions import RedisError  # type: ignore
    except Exception:  # pragma: no cover - redis always present
        RedisError = ()  # type: ignore

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=err(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=err(
                ErrorCode.VALIDATION_ERROR, "Request validation failed.",
                {"errors": exc.errors()},
            ),
        )

    @app.exception_handler(SQLAlchemyError)
    async def _db(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content=err(ErrorCode.DATABASE_ERROR, "Database error.", {"detail": str(exc)}),
        )

    if RedisError:
        @app.exception_handler(RedisError)
        async def _redis(_: Request, exc) -> JSONResponse:  # type: ignore
            return JSONResponse(
                status_code=503,
                content=err(ErrorCode.REDIS_ERROR, "Redis error.", {"detail": str(exc)}),
            )

    @app.exception_handler(Exception)
    async def _catch_all(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=err(ErrorCode.INTERNAL_ERROR, "Internal error.", {"detail": str(exc)}),
        )
