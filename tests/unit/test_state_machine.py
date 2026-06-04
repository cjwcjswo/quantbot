"""Tests for BotStateMachine (impl doc §3)."""

import pytest

from apps.bot.runtime import BotStateMachine, InvalidTransition
from packages.core.enums import BotState


def test_starts_in_booting():
    sm = BotStateMachine()
    assert sm.state == BotState.BOOTING


def test_boot_to_standby_is_allowed():
    sm = BotStateMachine()
    sm.transition(BotState.STANDBY)
    assert sm.state == BotState.STANDBY


def test_standby_cannot_jump_to_running():
    """Program start must not auto-start trading (impl doc §3.2)."""
    sm = BotStateMachine(initial=BotState.STANDBY)
    with pytest.raises(InvalidTransition):
        sm.transition(BotState.RUNNING)


def test_full_start_sequence():
    sm = BotStateMachine(initial=BotState.STANDBY)
    for state in (
        BotState.START_REQUESTED,
        BotState.SYNCING,
        BotState.READY,
        BotState.RUNNING,
    ):
        sm.transition(state)
    assert sm.state == BotState.RUNNING


def test_new_entries_only_in_running():
    sm = BotStateMachine(initial=BotState.STANDBY)
    blocked = [
        BotState.STANDBY,
        BotState.SYNCING,
        BotState.RECONCILING,
        BotState.ORDER_LOCKED,
        BotState.EMERGENCY_STOP,
        BotState.PAUSED,
        BotState.RISK_LOCKED,
    ]
    for state in blocked:
        sm.force(state)
        assert sm.can_enter_new_position() is False
    sm.force(BotState.RUNNING)
    assert sm.can_enter_new_position() is True


def test_running_can_pause_and_resume():
    sm = BotStateMachine(initial=BotState.RUNNING)
    sm.transition(BotState.PAUSED)
    assert not sm.can_enter_new_position()
    sm.transition(BotState.RUNNING)
    assert sm.can_enter_new_position()


def test_emergency_stop_terminal_path():
    sm = BotStateMachine(initial=BotState.RUNNING)
    sm.transition(BotState.EMERGENCY_STOP)
    sm.transition(BotState.STOPPING)
    sm.transition(BotState.STOPPED)
    assert sm.is_terminal()
    with pytest.raises(InvalidTransition):
        sm.transition(BotState.RUNNING)


def test_listener_invoked():
    sm = BotStateMachine()
    seen = []
    sm.add_listener(lambda a, b, r: seen.append((a, b)))
    sm.transition(BotState.STANDBY, reason="boot done")
    assert seen == [(BotState.BOOTING, BotState.STANDBY)]


def test_same_state_transition_is_noop():
    sm = BotStateMachine(initial=BotState.RUNNING)
    sm.transition(BotState.RUNNING)
    assert sm.state == BotState.RUNNING
