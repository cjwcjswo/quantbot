"""Storage stats + retention status queries (backend doc §25.10)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from apps.api.repositories.base import row_to_dict
from packages.storage.models import (
    BotEventRow,
    CommandLogRow,
    FillRow,
    ManualInterventionLogRow,
    OrderRow,
    PositionProtectionLogRow,
    PositionRow,
    ReconciliationLogRow,
    RetentionStatusRow,
    SignalRow,
    TradeRow,
)

_TABLES = {
    "bot_events": BotEventRow,
    "signals": SignalRow,
    "orders": OrderRow,
    "fills": FillRow,
    "positions": PositionRow,
    "trades": TradeRow,
    "command_logs": CommandLogRow,
    "reconciliation_logs": ReconciliationLogRow,
    "manual_intervention_logs": ManualInterventionLogRow,
    "position_protection_logs": PositionProtectionLogRow,
}


async def storage_stats(session_factory: Any) -> dict:
    tables = []
    async with session_factory() as s:
        for name, model in _TABLES.items():
            count = (await s.execute(
                select(func.count()).select_from(model))).scalar_one()
            oldest = (await s.execute(
                select(func.min(model.ts)))).scalar_one()
            tables.append({
                "name": name,
                "rows": int(count),
                "size_mb": None,
                "oldest_created_at": oldest.isoformat() if oldest else None,
            })
        status = (await s.execute(
            select(RetentionStatusRow).order_by(RetentionStatusRow.id.desc()).limit(1)
        )).scalar_one_or_none()
        # database size: Postgres only; SQLite/tests return None
        db_size = None
        try:
            db_size = (await s.execute(
                select(func.pg_database_size(func.current_database()))
            )).scalar_one()
            db_size = round(int(db_size) / (1024 * 1024), 2)
        except Exception:  # noqa: BLE001 - not Postgres
            db_size = None

    retention_status = row_to_dict(status) if status else {
        "last_cleanup_at": None, "last_archive_at": None,
        "last_summary_at": None, "last_health_check_at": None,
    }
    return {
        "database_size_mb": db_size,
        "tables": tables,
        "retention_status": retention_status,
    }
