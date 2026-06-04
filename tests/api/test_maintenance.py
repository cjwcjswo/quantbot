"""Backend doc §25.11: retention policy, summary, archive, cleanup, protection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from apps.api.maintenance import jobs
from apps.api.maintenance.retention_policy import RetentionPolicy, load_retention_policy
from packages.storage.models import (
    DailyPnlRow,
    DailySymbolPnlRow,
    OrderRow,
    OrdersArchiveRow,
    TradeRow,
)
from tests.api.conftest import add_rows


def _utc(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


async def _count(sf, model) -> int:
    async with sf() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


def test_policy_loads_defaults():
    p = load_retention_policy()
    assert p.keep_days("trades") == 1825
    assert p.archive_after_days("orders") == 365
    assert p.is_live_protected_table("trades") is True
    assert p.is_protected_event("EMERGENCY_STOP") is True


async def test_daily_summary_creates_rows(session_factory):
    day_dt = datetime(2026, 6, 4, 10, tzinfo=timezone.utc)
    await add_rows(session_factory, TradeRow(
        trade_id="t1", symbol="BTCUSDT", side="LONG", qty="0.01",
        entry_price="65000", exit_price="67000", realized_pnl="20", net_pnl="18",
        fees="2", strategy_id="trend_following", entry_mode="RETEST_CONFIRM",
        mode="PAPER", closed_at=day_dt))
    await jobs.daily_summary(session_factory, RetentionPolicy(), day="2026-06-04")
    assert await _count(session_factory, DailySymbolPnlRow) == 1
    assert await _count(session_factory, DailyPnlRow) == 1


async def test_archive_moves_old_rows(session_factory):
    await add_rows(session_factory, OrderRow(
        symbol="BTCUSDT", side="Buy", order_type="LIMIT", qty="0.01",
        status="FILLED", mode="PAPER", order_id="old", ts=_utc(400)))
    moved = await jobs.archive_job(session_factory, RetentionPolicy())
    assert moved == 1
    assert await _count(session_factory, OrdersArchiveRow) == 1
    # PAPER order is not delete-protected -> original removed
    assert await _count(session_factory, OrderRow) == 0


async def test_cleanup_protects_live_and_respects_summary(session_factory):
    # a LIVE trade older than keep_days must survive cleanup (archive-only)
    await add_rows(
        session_factory,
        TradeRow(trade_id="live", symbol="BTCUSDT", side="LONG", qty="1",
                 entry_price="1", exit_price="2", realized_pnl="1", mode="LIVE",
                 ts=_utc(2000)),
        TradeRow(trade_id="paper", symbol="ETHUSDT", side="LONG", qty="1",
                 entry_price="1", exit_price="2", realized_pnl="1", mode="PAPER",
                 ts=_utc(2000)),
        DailyPnlRow(day="2020-01-01", realized="0", unrealized="0", fees="0", net="0"),
    )
    await jobs.retention_cleanup(session_factory, RetentionPolicy())
    async with session_factory() as s:
        ids = set((await s.execute(select(TradeRow.trade_id))).scalars().all())
    assert "live" in ids       # LIVE protected
    assert "paper" not in ids  # PAPER deleted (summary present)


async def test_cleanup_skips_paper_without_summary(session_factory):
    await add_rows(session_factory, TradeRow(
        trade_id="paper", symbol="ETHUSDT", side="LONG", qty="1",
        entry_price="1", exit_price="2", realized_pnl="1", mode="PAPER",
        ts=_utc(2000)))
    # no DailyPnlRow -> summary_exists False -> PAPER detail not deleted
    await jobs.retention_cleanup(session_factory, RetentionPolicy())
    assert await _count(session_factory, TradeRow) == 1


async def test_health_check_false_on_broken_factory():
    class BoomSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, *a):
            raise RuntimeError("db down")

    def boom_sf():
        return BoomSession()

    assert await jobs.database_health_check(boom_sf) is False
