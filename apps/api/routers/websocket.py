"""Dashboard WebSocket router (backend doc §17)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from apps.api.services import realtime_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/dashboard")
async def dashboard_ws(ws: WebSocket) -> None:
    st = ws.app.state
    manager = st.ws_hub
    await manager.connect(ws)
    # send the latest snapshot immediately on connect (§17 connection policy)
    try:
        snapshot = await realtime_service.build_snapshot(
            st.redis, st.session_factory, st.api_settings)
        await ws.send_json({"type": "snapshot", "data": snapshot})
    except Exception as exc:  # noqa: BLE001
        logger.warning("snapshot send failed: %s", exc)
    try:
        while True:
            # keep the connection open; clients are receive-only.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws error: %s", exc)
    finally:
        manager.disconnect(ws)
