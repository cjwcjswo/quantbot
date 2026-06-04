"""Storage stats service (backend doc §25.10)."""

from __future__ import annotations

from typing import Any

from apps.api.repositories import maintenance_repository


async def storage(session_factory: Any) -> dict:
    return await maintenance_repository.storage_stats(session_factory)
