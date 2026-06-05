"""StatePublisher: pushes realtime Bot Engine state to Redis (arch doc §6.24, §10.8).

Backend API reads these keys to drive the dashboard. Values are JSON strings.
"""

from __future__ import annotations

import json
import time
from typing import Any

from packages.core.enums import BotMode, BotState, PositionStatus
from packages.core.models import Position
from packages.messaging import state_keys


def _protection_status(
    p: Position, *, require_sl: bool = True, require_tp: bool = True
) -> str:
    if not require_sl and not require_tp:
        return "NOT_REQUIRED"
    if require_sl and p.stop_loss_price is None:
        return "TPSL_PENDING"
    if require_tp and p.take_profit_price is None:
        return "TPSL_PENDING"
    return "TPSL_OK"


def _position_json(
    p: Position,
    mode: BotMode | None = None,
    *,
    require_sl: bool = True,
    require_tp: bool = True,
) -> dict:
    return {
        "symbol": p.symbol,
        "side": p.side.value,
        "status": p.status.value,
        "source": p.source.value,
        "mode": mode.value if mode is not None else None,
        "qty": str(p.qty),
        "avg_entry_price": str(p.avg_entry_price),
        "manual_added_qty": str(p.manual_added_qty),
        "leverage": str(p.leverage),
        "mark_price": None,
        "strategy_id": p.strategy_id or None,
        "protection_status": _protection_status(
            p, require_sl=require_sl, require_tp=require_tp
        ),
        "stop_loss": str(p.stop_loss_price) if p.stop_loss_price is not None else None,
        "take_profit": str(p.take_profit_price) if p.take_profit_price is not None else None,
        "unrealized_pnl": str(p.unrealized_pnl),
        "entry_mode": p.entry_mode.value if p.entry_mode else None,
    }


def _is_open_position(p: Position) -> bool:
    return p.status in (
        PositionStatus.PENDING,
        PositionStatus.ACTIVE,
        PositionStatus.CLOSING,
    )


class StatePublisher:
    def __init__(
        self,
        redis: Any | None,
        mode: BotMode,
        *,
        require_sl: bool = True,
        require_tp: bool = True,
    ) -> None:
        self._redis = redis
        self._mode = mode
        self._require_sl = require_sl
        self._require_tp = require_tp

    async def publish(
        self,
        *,
        state: BotState,
        positions: list[Position] | None = None,
        pnl: dict | None = None,
        risk_status: dict | None = None,
        protection_status: dict | None = None,
        reconciliation_status: dict | None = None,
    ) -> None:
        if self._redis is None:
            return
        await self._redis.set(state_keys.BOT_STATUS, state.value)
        await self._redis.set(state_keys.BOT_MODE, self._mode.value)
        await self._redis.set(state_keys.BOT_HEARTBEAT, str(int(time.time() * 1000)))
        if positions is not None:
            open_positions = [p for p in positions if _is_open_position(p)]
            await self._redis.set(
                state_keys.BOT_POSITIONS,
                json.dumps([
                    _position_json(
                        p,
                        self._mode,
                        require_sl=self._require_sl,
                        require_tp=self._require_tp,
                    )
                    for p in open_positions
                ]),
            )
        if pnl is not None:
            await self._redis.set(state_keys.BOT_PNL, json.dumps(pnl))
        if risk_status is not None:
            await self._redis.set(state_keys.BOT_RISK_STATUS, json.dumps(risk_status))
        if protection_status is not None:
            await self._redis.set(
                state_keys.BOT_PROTECTION_STATUS, json.dumps(protection_status)
            )
        if reconciliation_status is not None:
            await self._redis.set(
                state_keys.BOT_RECONCILIATION_STATUS,
                json.dumps(reconciliation_status),
            )

    async def publish_watchlist(self, entries: list[dict]) -> None:
        """Publish the scanner candidates + per-symbol entry preview (arch §6.24)."""
        if self._redis is None:
            return
        await self._redis.set(state_keys.BOT_WATCHLIST, json.dumps(entries))
