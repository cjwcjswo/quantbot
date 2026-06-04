"""Small shared helpers for routers."""

from __future__ import annotations

from datetime import datetime

from apps.api import errors


def parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise errors.ApiError(
            errors.ErrorCode.VALIDATION_ERROR, f"Invalid datetime: {value}")
