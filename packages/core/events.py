"""Bot event taxonomy (arch doc §7 bot_events, impl doc §4, §5, §17).

Events are published to Redis (``events:bot``) for the dashboard and persisted
to PostgreSQL for audit. The enum is the single source of event type strings.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class BotEventType(StrEnum):
    # lifecycle / state
    STATE_CHANGED = "STATE_CHANGED"
    COMMAND_RECEIVED = "COMMAND_RECEIVED"
    COMMAND_FAILED = "COMMAND_FAILED"

    # reconciliation / manual intervention (impl doc §4)
    RECONCILED = "RECONCILED"
    EXTERNAL_POSITION_DETECTED = "EXTERNAL_POSITION_DETECTED"
    EXTERNAL_ORDER_DETECTED = "EXTERNAL_ORDER_DETECTED"
    POSITION_QUANTITY_MISMATCH = "POSITION_QUANTITY_MISMATCH"
    MANUAL_PARTIAL_CLOSE_DETECTED = "MANUAL_PARTIAL_CLOSE_DETECTED"
    MANUAL_ADD_DETECTED = "MANUAL_ADD_DETECTED"
    POSITION_CLOSED_EXTERNALLY = "POSITION_CLOSED_EXTERNALLY"
    RISK_LIMIT_EXCEEDED_BY_MANUAL_INTERVENTION = (
        "RISK_LIMIT_EXCEEDED_BY_MANUAL_INTERVENTION"
    )

    # protection / emergency (impl doc §5, §17)
    TPSL_SET = "TPSL_SET"
    TPSL_VERIFIED = "TPSL_VERIFIED"
    EMERGENCY_TPSL_FAILED = "EMERGENCY_TPSL_FAILED"
    EMERGENCY_CLOSE = "EMERGENCY_CLOSE"

    # trading lifecycle
    SIGNAL = "SIGNAL"
    ORDER_PLACED = "ORDER_PLACED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_FAILED = "ORDER_FAILED"
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_CLOSED = "POSITION_CLOSED"

    # guards / kill switch (impl doc §7, §15)
    KILL_SWITCH_TRIPPED = "KILL_SWITCH_TRIPPED"
    DATA_QUALITY_BLOCK = "DATA_QUALITY_BLOCK"
    NEW_ENTRIES_PAUSED = "NEW_ENTRIES_PAUSED"


class BotEvent(BaseModel):
    """A structured event emitted by the Bot Engine."""

    model_config = ConfigDict(frozen=True)

    type: BotEventType
    symbol: str | None = None
    message: str = ""
    data: dict = Field(default_factory=dict)
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
