"""Backend doc §23 Phase 7: WebSocket manager + stream behaviors."""

from __future__ import annotations

import json

from apps.api.config import ApiSettings
from apps.api.services import realtime_service
from apps.api.websocket import ConnectionManager
from apps.api.websocket.dashboard_stream import DashboardStream, classify_event


class FakeWS:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list = []
        self.fail = fail
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, msg: dict) -> None:
        if self.fail:
            raise RuntimeError("dead socket")
        self.sent.append(msg)


class RecordingManager:
    def __init__(self) -> None:
        self.messages: list = []

    async def broadcast(self, msg: dict) -> None:
        self.messages.append(msg)


def test_classify_event():
    assert classify_event("POSITION_OPENED") == "position_update"
    assert classify_event("TPSL_SET") == "protection_update"
    assert classify_event("SIGNAL") == "bot_event"


async def test_connection_manager_drops_dead_socket():
    mgr = ConnectionManager()
    good, bad = FakeWS(), FakeWS(fail=True)
    await mgr.connect(good)
    await mgr.connect(bad)
    await mgr.broadcast({"type": "x"})
    assert good.sent and bad not in mgr.active
    mgr.disconnect(good)
    assert good not in mgr.active


async def test_dispatch_event_classifies(redis):
    mgr = RecordingManager()
    stream = DashboardStream(redis, mgr, ApiSettings())
    await stream.dispatch_event(json.dumps({"type": "POSITION_OPENED", "symbol": "BTC"}))
    assert mgr.messages[0]["type"] == "position_update"


async def test_pnl_throttle(redis):
    mgr = RecordingManager()
    stream = DashboardStream(redis, mgr, ApiSettings())
    await redis.set("bot:pnl", json.dumps({"realized": "1"}))
    await stream.push_pnl_if_due()
    await redis.set("bot:pnl", json.dumps({"realized": "2"}))
    await stream.push_pnl_if_due()  # within 1s -> throttled
    assert sum(1 for m in mgr.messages if m["type"] == "pnl_update") == 1


async def test_positions_pushed_on_change(redis):
    mgr = RecordingManager()
    stream = DashboardStream(redis, mgr, ApiSettings())
    await redis.set("bot:positions", json.dumps([{"symbol": "BTCUSDT"}]))
    await stream.push_positions_if_changed()
    await stream.push_positions_if_changed()  # unchanged -> no second push
    assert sum(1 for m in mgr.messages if m["type"] == "position_update") == 1


async def test_build_snapshot(redis, session_factory):
    await redis.set("bot:status", "STANDBY")
    await redis.set("bot:mode", "PAPER")
    snap = await realtime_service.build_snapshot(redis, session_factory, ApiSettings())
    assert "bot_status" in snap
    assert "positions" in snap
    assert "pnl" in snap
    assert "watchlist" in snap


async def test_watchlist_pushed_on_change(redis):
    mgr = RecordingManager()
    stream = DashboardStream(redis, mgr, ApiSettings())
    await redis.set("bot:watchlist", json.dumps([{"symbol": "BTCUSDT", "readiness": "NEAR"}]))
    await stream.push_watchlist_if_changed()
    await stream.push_watchlist_if_changed()  # unchanged -> no second push
    assert sum(1 for m in mgr.messages if m["type"] == "watchlist_update") == 1
