"""Tests for BotRuntime extras: ws-disconnect policy, PnL persistence, clock sync."""

from decimal import Decimal

from sqlalchemy import func, select

from apps.bot.runtime import BotRuntime
from packages.config import load_app_config
from packages.config.settings import Secrets
from packages.core.enums import BotMode, BotState
from packages.guards import ClockSyncGuard
from packages.reconciliation.reconciliation_manager import ReconcileResult
from packages.storage import (
    DailyPnlRow,
    PaperAccountSnapshotRow,
    ReconciliationLogRow,
    TradeLogger,
)
from tests.fakes import FakeGateway
from tests.fakes.builders import ticker


def _runtime(redis, session_factory, gateway=None, *, mode=None):
    cfg = load_app_config("config/quantbot.yaml")
    if mode is not None:
        cfg.bot.mode = mode
    return BotRuntime(
        cfg, Secrets(), redis=redis, gateway=gateway or FakeGateway(),
        trade_logger=TradeLogger(session_factory),
    )


async def _count(sf, model):
    async with sf() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


async def test_ws_disconnect_recovers_to_running(redis, session_factory):
    rt = _runtime(redis, session_factory)
    await rt.startup()
    rt.state_machine.force(BotState.RUNNING, reason="test")
    before = await _count(session_factory, ReconciliationLogRow)  # startup reconcile = 1
    await rt._handle_ws_disconnect()
    assert rt.state_machine.state == BotState.RUNNING
    # a fresh reconciliation ran during recovery (§17.2)
    assert await _count(session_factory, ReconciliationLogRow) == before + 1
    await rt.shutdown()


async def test_reconciliation_mismatch_trips_risk_lock(redis, session_factory):
    rt = _runtime(redis, session_factory)
    await rt.startup()
    rt.state_machine.force(BotState.RUNNING, reason="test")
    rt._record_reconciliation_risk(ReconcileResult(qty_mismatches=["BTCUSDT"]))
    await rt._apply_kill_switch_trip()
    assert rt.state_machine.state == BotState.RISK_LOCKED
    await rt.shutdown()


async def test_pnl_persisted(redis, session_factory):
    rt = _runtime(redis, session_factory, mode=BotMode.PAPER)
    await rt.startup()
    await rt._publish_and_persist_pnl()
    assert await _count(session_factory, DailyPnlRow) == 1
    # PAPER mode also snapshots the virtual account
    assert await _count(session_factory, PaperAccountSnapshotRow) == 1
    # bot:pnl key published
    assert await redis.get("bot:pnl") is not None
    await rt.shutdown()


async def test_state_publish_includes_risk_protection_reconciliation(redis, session_factory):
    rt = _runtime(redis, session_factory)
    await rt.startup()
    await rt._publish_state()
    assert await redis.get("bot:risk_status") is not None
    assert await redis.get("bot:protection_status") is not None
    assert await redis.get("bot:reconciliation_status") is not None
    await rt.shutdown()


async def test_private_ws_event_runs_reconciliation(redis, session_factory):
    rt = _runtime(redis, session_factory)
    await rt.startup()
    before = await _count(session_factory, ReconciliationLogRow)
    await rt._handle_private_event("order", {"data": []})
    assert await _count(session_factory, ReconciliationLogRow) == before + 1
    await rt.shutdown()


async def test_clock_sync_uses_server_time(redis, session_factory):
    gw = FakeGateway()
    gw.server_time_ms = 1_700_000_000_000
    rt = _runtime(redis, session_factory, gateway=gw)
    await rt.startup()
    # server time available + guard wired
    assert await rt._gateway.get_server_time() == 1_700_000_000_000
    guard = ClockSyncGuard()
    guard.update(await rt._gateway.get_server_time(), local_time_ms=1_700_000_000_300)
    assert guard.drift_ms == 300
    await rt.shutdown()
