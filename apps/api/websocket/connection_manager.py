"""ConnectionManager: tracks dashboard WebSocket clients (backend doc §17)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.active: set[Any] = set()

    async def connect(self, ws: Any) -> None:
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: Any) -> None:
        self.active.discard(ws)

    async def send(self, ws: Any, message: dict) -> None:
        await ws.send_json(message)

    async def broadcast(self, message: dict) -> None:
        """Send to every client; drop any socket that errors (per-socket isolation)."""
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 - one dead socket must not stop the rest
                dead.append(ws)
        for ws in dead:
            self.active.discard(ws)
