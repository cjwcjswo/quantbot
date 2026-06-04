"""DashboardStream: bridges Redis (events:bot pub/sub + bot:* snapshots) to clients.

Backend doc §17: state-change events push immediately, pnl_update throttled to
<=1/s, heartbeat (bot_status) every 5s, snapshot sent on connect by the router.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from packages.messaging import state_keys

logger = logging.getLogger(__name__)

# BotEventType.value -> dashboard ws event type
_EVENT_MAP = {
    "POSITION_OPENED": "position_update",
    "POSITION_CLOSED": "position_update",
    "ORDER_PLACED": "order_update",
    "ORDER_FILLED": "order_update",
    "ORDER_FAILED": "order_update",
    "TPSL_SET": "protection_update",
    "TPSL_VERIFIED": "protection_update",
    "EMERGENCY_TPSL_FAILED": "protection_update",
    "EMERGENCY_CLOSE": "protection_update",
    "RECONCILED": "reconciliation_update",
    "EXTERNAL_POSITION_DETECTED": "manual_intervention_event",
    "EXTERNAL_ORDER_DETECTED": "manual_intervention_event",
    "POSITION_QUANTITY_MISMATCH": "manual_intervention_event",
    "MANUAL_PARTIAL_CLOSE_DETECTED": "manual_intervention_event",
    "MANUAL_ADD_DETECTED": "manual_intervention_event",
    "RISK_LIMIT_EXCEEDED_BY_MANUAL_INTERVENTION": "manual_intervention_event",
    "KILL_SWITCH_TRIPPED": "risk_update",
}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def classify_event(event_type: str) -> str:
    return _EVENT_MAP.get(event_type, "bot_event")


class DashboardStream:
    def __init__(self, redis: Any, manager: Any, api_settings: Any) -> None:
        self._redis = redis
        self._manager = manager
        self._settings = api_settings
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._last_pnl_sent = 0.0
        self._last_positions_raw: str | None = None
        self._last_watchlist_raw: str | None = None

    async def start(self) -> None:
        self._running = True
        self._tasks = [
            asyncio.create_task(self._pubsub_loop()),
            asyncio.create_task(self._snapshot_loop()),
            asyncio.create_task(self._heartbeat_loop()),
        ]

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks = []

    # ------------------------------------------------------------------ #
    def _wrap(self, type_: str, data: Any) -> dict:
        return {"type": type_, "timestamp": _now_iso(), "data": data}

    async def dispatch_event(self, raw: str) -> None:
        """Classify a raw BotEvent JSON and broadcast it (used by pubsub loop + tests)."""
        try:
            event = json.loads(raw)
        except (ValueError, TypeError):
            return
        ws_type = classify_event(str(event.get("type", "")))
        await self._manager.broadcast(self._wrap(ws_type, event))

    async def build_bot_status(self) -> dict:
        try:
            status = await self._redis.get(state_keys.BOT_STATUS)
            mode = await self._redis.get(state_keys.BOT_MODE)
            hb = await self._redis.get(state_keys.BOT_HEARTBEAT)
        except Exception:  # noqa: BLE001
            return {"state": "UNKNOWN", "degraded": True}
        is_alive = False
        if hb:
            try:
                age_ms = int(time.time() * 1000) - int(hb)
                is_alive = age_ms <= self._settings.heartbeat_alive_sec * 1000
            except (ValueError, TypeError):
                is_alive = False
        return {
            "state": status or "UNKNOWN",
            "mode": mode,
            "heartbeat_at": hb,
            "is_alive": is_alive,
        }

    async def push_bot_status(self) -> None:
        await self._manager.broadcast(self._wrap("bot_status", await self.build_bot_status()))

    async def push_pnl_if_due(self) -> None:
        now = time.monotonic()
        if now - self._last_pnl_sent < 1.0:
            return
        try:
            raw = await self._redis.get(state_keys.BOT_PNL)
        except Exception:  # noqa: BLE001
            return
        if raw is None:
            return
        self._last_pnl_sent = now
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = {"raw": raw}
        await self._manager.broadcast(self._wrap("pnl_update", data))

    async def push_positions_if_changed(self) -> None:
        try:
            raw = await self._redis.get(state_keys.BOT_POSITIONS)
        except Exception:  # noqa: BLE001
            return
        if raw is None or raw == self._last_positions_raw:
            return
        self._last_positions_raw = raw
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return
        await self._manager.broadcast(self._wrap("position_update", data))

    async def push_watchlist_if_changed(self) -> None:
        try:
            raw = await self._redis.get(state_keys.BOT_WATCHLIST)
        except Exception:  # noqa: BLE001
            return
        if raw is None or raw == self._last_watchlist_raw:
            return
        self._last_watchlist_raw = raw
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return
        await self._manager.broadcast(self._wrap("watchlist_update", data))

    # ------------------------------------------------------------------ #
    async def _pubsub_loop(self) -> None:
        while self._running:
            pubsub = self._redis.pubsub()
            try:
                await pubsub.subscribe(state_keys.EVENTS_BOT)
                while self._running:
                    # Poll with a timeout: an idle window returns None (normal),
                    # so we don't misclassify "no events yet" as a connection
                    # error and churn through reconnects (which dropped events
                    # and spammed warnings).
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )
                    if message is None:
                        continue
                    if message.get("type") == "message":
                        await self.dispatch_event(message.get("data"))
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - real pub/sub failure: degrade + retry
                logger.warning("pubsub loop error: %s", exc)
                await self._manager.broadcast(
                    self._wrap("bot_status", {"degraded": True})
                )
                await asyncio.sleep(3)
            finally:
                close = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
                if close is not None:
                    try:
                        await close()
                    except Exception:  # noqa: BLE001
                        pass

    async def _snapshot_loop(self) -> None:
        while self._running:
            try:
                await self.push_pnl_if_due()
                await self.push_positions_if_changed()
                await self.push_watchlist_if_changed()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("snapshot loop error: %s", exc)
            await asyncio.sleep(1)

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                await self.push_bot_status()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("heartbeat loop error: %s", exc)
            await asyncio.sleep(5)
