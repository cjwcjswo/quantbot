"""Backend doc §25.10: /system/storage."""

from __future__ import annotations

from packages.storage.models import BotEventRow
from tests.api.conftest import add_rows


async def test_storage_stats(client, session_factory):
    await add_rows(session_factory, BotEventRow(type="SIGNAL", symbol="BTCUSDT"))
    data = (await client.get("/system/storage")).json()["data"]
    tables = {t["name"]: t for t in data["tables"]}
    assert tables["bot_events"]["rows"] == 1
    # SQLite -> no pg_database_size
    assert data["database_size_mb"] is None
    assert "retention_status" in data
