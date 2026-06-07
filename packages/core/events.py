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
    NO_ENTRY_REASON = "NO_ENTRY_REASON"
    ORDER_PLACED = "ORDER_PLACED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_FAILED = "ORDER_FAILED"
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_CLOSED = "POSITION_CLOSED"
    SCOUT_PENDING_STARTED = "SCOUT_PENDING_STARTED"
    SCOUT_WARNING_STARTED = "SCOUT_WARNING_STARTED"
    SCOUT_WARNING_RECOVERED = "SCOUT_WARNING_RECOVERED"
    SCOUT_CONFIRMED = "SCOUT_CONFIRMED"
    SCOUT_ACTIVATED = "SCOUT_ACTIVATED"
    SCOUT_DEFENSIVE_REDUCE = "SCOUT_DEFENSIVE_REDUCE"
    SCOUT_CATASTROPHIC_REDUCE = "SCOUT_CATASTROPHIC_REDUCE"
    SCOUT_INVALIDATED = "SCOUT_INVALIDATED"
    SCENARIO_INVALID_REDUCE = "SCENARIO_INVALID_REDUCE"
    STAGNATION_REDUCE = "STAGNATION_REDUCE"
    RUNNER_MODE_ACTIVATED = "RUNNER_MODE_ACTIVATED"
    RUNNER_TREND_STRENGTH_CHANGED = "RUNNER_TREND_STRENGTH_CHANGED"
    RUNNER_TRAILING_UPDATED = "RUNNER_TRAILING_UPDATED"
    RUNNER_EXCHANGE_SL_UPDATED = "RUNNER_EXCHANGE_SL_UPDATED"
    RUNNER_EXCHANGE_SL_UPDATE_FAILED = "RUNNER_EXCHANGE_SL_UPDATE_FAILED"
    RUNNER_TRAILING_STOP = "RUNNER_TRAILING_STOP"
    RUNNER_SCENARIO_INVALID = "RUNNER_SCENARIO_INVALID"
    RUNNER_POST_EXIT_MFE = "RUNNER_POST_EXIT_MFE"

    # guards / kill switch (impl doc §7, §15)
    KILL_SWITCH_TRIPPED = "KILL_SWITCH_TRIPPED"
    DATA_QUALITY_BLOCK = "DATA_QUALITY_BLOCK"
    NEW_ENTRIES_PAUSED = "NEW_ENTRIES_PAUSED"


_CRITICAL_EVENTS = {
    "EMERGENCY_STOP",
    "EMERGENCY_CLOSE",
    "EMERGENCY_TPSL_FAILED",
}
_ERROR_EVENTS = {
    "COMMAND_FAILED",
    "TPSL_FAILED",
    "ORDER_FAILED",
    "KILL_SWITCH_TRIPPED",
    "RISK_LOCKED",
    "ORDER_LOCKED",
}
_WARNING_EVENTS = {
    "NEW_ENTRIES_PAUSED",
    "EXTERNAL_POSITION_DETECTED",
    "EXTERNAL_ORDER_DETECTED",
    "POSITION_QUANTITY_MISMATCH",
    "MANUAL_PARTIAL_CLOSE_DETECTED",
    "MANUAL_ADD_DETECTED",
    "POSITION_CLOSED_EXTERNALLY",
    "RISK_LIMIT_EXCEEDED_BY_MANUAL_INTERVENTION",
    "RUNNER_EXCHANGE_SL_UPDATE_FAILED",
}
_SEVERITY_TO_EVENTS = {
    "CRITICAL": _CRITICAL_EVENTS,
    "ERROR": _ERROR_EVENTS,
    "WARNING": _WARNING_EVENTS,
}
_IMPORTANT_INFO_EVENTS = {
    "NO_ENTRY_REASON",
    "ORDER_PLACED",
    "ORDER_FILLED",
    "POSITION_OPENED",
    "POSITION_CLOSED",
    "SCOUT_PENDING_STARTED",
    "SCOUT_WARNING_STARTED",
    "SCOUT_WARNING_RECOVERED",
    "SCOUT_CONFIRMED",
    "SCOUT_ACTIVATED",
    "SCOUT_DEFENSIVE_REDUCE",
    "SCOUT_CATASTROPHIC_REDUCE",
    "SCOUT_INVALIDATED",
    "SCENARIO_INVALID_REDUCE",
    "STAGNATION_REDUCE",
    "RUNNER_MODE_ACTIVATED",
    "RUNNER_TREND_STRENGTH_CHANGED",
    "RUNNER_TRAILING_UPDATED",
    "RUNNER_EXCHANGE_SL_UPDATED",
    "RUNNER_TRAILING_STOP",
    "RUNNER_SCENARIO_INVALID",
    "RUNNER_POST_EXIT_MFE",
}


def event_severity(event_type: str | BotEventType, stored: str | None = None) -> str:
    if stored and stored != "INFO":
        return stored.upper()
    value = event_type.value if isinstance(event_type, BotEventType) else event_type
    for severity, event_types in _SEVERITY_TO_EVENTS.items():
        if value in event_types:
            return severity
    return (stored or "INFO").upper()


def event_types_for_severity(severity: str) -> set[str]:
    return set(_SEVERITY_TO_EVENTS.get(severity.upper(), set()))


def non_info_event_types() -> set[str]:
    out: set[str] = set()
    for event_types in _SEVERITY_TO_EVENTS.values():
        out.update(event_types)
    return out


def should_persist_event(
    event_type: str | BotEventType, stored_severity: str | None = None
) -> bool:
    value = event_type.value if isinstance(event_type, BotEventType) else event_type
    severity = event_severity(value, stored_severity)
    if severity == "INFO":
        return value in _IMPORTANT_INFO_EVENTS
    if severity == "WARNING":
        return value in _WARNING_EVENTS
    return severity in {"ERROR", "CRITICAL"}


class BotEvent(BaseModel):
    """A structured event emitted by the Bot Engine."""

    model_config = ConfigDict(frozen=True)

    type: BotEventType
    symbol: str | None = None
    message: str = ""
    data: dict = Field(default_factory=dict)
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
