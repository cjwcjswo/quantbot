"""Bot Engine state machine (impl doc §3, arch doc §6.4).

Enforces the two cardinal rules:

1. Program start only auto-advances ``BOOTING -> STANDBY``. The jump to RUNNING
   must go through ``STANDBY -> START_REQUESTED -> SYNCING -> READY -> RUNNING``
   and is only triggered by a user START command.
2. New entries are only allowed in RUNNING (``can_enter_new_position``). STANDBY,
   RECONCILING, ORDER_LOCKED, EMERGENCY_STOP, PAUSED, RISK_LOCKED all block.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from packages.core.enums import BotState
from packages.core.errors import QuantBotError

logger = logging.getLogger(__name__)

TransitionListener = Callable[[BotState, BotState, str], None]

# Allowed transitions. A target absent from a source's set is rejected.
_ALLOWED: dict[BotState, frozenset[BotState]] = {
    BotState.BOOTING: frozenset({BotState.STANDBY, BotState.STOPPING}),
    BotState.STANDBY: frozenset({BotState.START_REQUESTED, BotState.STOPPING}),
    BotState.START_REQUESTED: frozenset(
        {BotState.SYNCING, BotState.STANDBY, BotState.STOPPING}
    ),
    BotState.SYNCING: frozenset(
        {
            BotState.READY,
            BotState.STANDBY,
            BotState.RECONCILING,
            BotState.EMERGENCY_STOP,
            BotState.STOPPING,
        }
    ),
    BotState.READY: frozenset(
        {BotState.RUNNING, BotState.STANDBY, BotState.STOPPING}
    ),
    BotState.RUNNING: frozenset(
        {
            BotState.PAUSED,
            BotState.RISK_LOCKED,
            BotState.RECONCILING,
            BotState.ORDER_LOCKED,
            BotState.EMERGENCY_STOP,
            BotState.STOPPING,
        }
    ),
    BotState.PAUSED: frozenset(
        {
            BotState.RUNNING,
            BotState.RISK_LOCKED,
            BotState.RECONCILING,
            BotState.EMERGENCY_STOP,
            BotState.STOPPING,
        }
    ),
    BotState.RISK_LOCKED: frozenset(
        {
            BotState.RUNNING,
            BotState.PAUSED,
            BotState.EMERGENCY_STOP,
            BotState.STOPPING,
        }
    ),
    BotState.RECONCILING: frozenset(
        {
            BotState.RUNNING,
            BotState.PAUSED,
            BotState.STANDBY,
            BotState.ORDER_LOCKED,
            BotState.EMERGENCY_STOP,
            BotState.STOPPING,
        }
    ),
    BotState.ORDER_LOCKED: frozenset(
        {
            BotState.RECONCILING,
            BotState.RUNNING,
            BotState.EMERGENCY_STOP,
            BotState.STOPPING,
        }
    ),
    BotState.EMERGENCY_STOP: frozenset(
        {BotState.STOPPING, BotState.STOPPED}
    ),
    BotState.STOPPING: frozenset({BotState.STOPPED}),
    BotState.STOPPED: frozenset(),
}

# States in which new entries are permitted (impl doc §3.1, arch doc §6.4).
_ENTRY_ALLOWED_STATES: frozenset[BotState] = frozenset({BotState.RUNNING})

# States that still permit managing existing bot positions / closing them.
_MANAGEMENT_ALLOWED_STATES: frozenset[BotState] = frozenset(
    {
        BotState.RUNNING,
        BotState.PAUSED,
        BotState.RISK_LOCKED,
        BotState.ORDER_LOCKED,
        BotState.RECONCILING,
        BotState.EMERGENCY_STOP,
    }
)

_TERMINAL_STATES: frozenset[BotState] = frozenset({BotState.STOPPED})


class InvalidTransition(QuantBotError):
    """Raised when a state transition is not permitted by the transition table."""

    def __init__(self, from_state: BotState, to_state: BotState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Invalid transition: {from_state} -> {to_state}")


class BotStateMachine:
    """Tracks and guards the Bot Engine execution state."""

    def __init__(self, initial: BotState = BotState.BOOTING) -> None:
        self._state = initial
        self._listeners: list[TransitionListener] = []

    @property
    def state(self) -> BotState:
        return self._state

    def add_listener(self, listener: TransitionListener) -> None:
        """Register a callback invoked after every successful transition."""
        self._listeners.append(listener)

    def can_transition(self, to_state: BotState) -> bool:
        return to_state in _ALLOWED.get(self._state, frozenset())

    def transition(self, to_state: BotState, reason: str = "") -> None:
        """Move to ``to_state`` or raise :class:`InvalidTransition`."""
        if to_state == self._state:
            return
        if not self.can_transition(to_state):
            raise InvalidTransition(self._state, to_state)
        from_state = self._state
        self._state = to_state
        logger.info("State transition %s -> %s (%s)", from_state, to_state, reason)
        for listener in self._listeners:
            try:
                listener(from_state, to_state, reason)
            except Exception:  # never let a listener break the state machine
                logger.exception("State transition listener failed")

    def force(self, to_state: BotState, reason: str = "forced") -> None:
        """Unconditionally set the state (used for emergency paths only)."""
        from_state = self._state
        self._state = to_state
        logger.warning("State FORCED %s -> %s (%s)", from_state, to_state, reason)
        for listener in self._listeners:
            try:
                listener(from_state, to_state, reason)
            except Exception:
                logger.exception("State transition listener failed")

    # ---- guards ---------------------------------------------------------- #
    def can_enter_new_position(self) -> bool:
        """True only in RUNNING (impl doc §3.1)."""
        return self._state in _ENTRY_ALLOWED_STATES

    def can_manage_positions(self) -> bool:
        """True in states where existing bot positions may still be managed/closed."""
        return self._state in _MANAGEMENT_ALLOWED_STATES

    def is_terminal(self) -> bool:
        return self._state in _TERMINAL_STATES
