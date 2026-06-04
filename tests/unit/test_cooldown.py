"""Tests for CooldownTracker (impl doc §7 cooldown)."""

from packages.core.enums import EntryMode
from packages.position import CooldownTracker


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_single_loss_symbol_cooldown(config):
    clock = FakeClock()
    ct = CooldownTracker(config.cooldown, clock=clock)
    ct.record_result("BTCUSDT", EntryMode.BREAKOUT_CONFIRM, is_win=False)
    assert ct.in_symbol_cooldown("BTCUSDT")
    clock.t = 16 * 60  # past 15min single-loss window
    assert not ct.in_symbol_cooldown("BTCUSDT")


def test_two_losses_extends_to_60min(config):
    clock = FakeClock()
    ct = CooldownTracker(config.cooldown, clock=clock)
    ct.record_result("BTCUSDT", EntryMode.BREAKOUT_CONFIRM, is_win=False)
    clock.t = 10 * 60
    ct.record_result("BTCUSDT", EntryMode.BREAKOUT_CONFIRM, is_win=False)
    clock.t = 20 * 60  # past 15min but within 60min of 2 losses
    assert ct.in_symbol_cooldown("BTCUSDT")
    clock.t = 71 * 60
    assert not ct.in_symbol_cooldown("BTCUSDT")


def test_global_cooldown_after_3_losses(config):
    clock = FakeClock()
    ct = CooldownTracker(config.cooldown, clock=clock)
    for sym in ("A", "B", "C"):
        ct.record_result(sym, EntryMode.BREAKOUT_CONFIRM, is_win=False)
    assert ct.in_global_cooldown()
    clock.t = 31 * 60  # window passed
    assert not ct.in_global_cooldown()


def test_entry_mode_cooldown(config):
    clock = FakeClock()
    ct = CooldownTracker(config.cooldown, clock=clock)
    ct.record_result("BTCUSDT", EntryMode.RETEST_CONFIRM, is_win=False)
    assert ct.in_entry_mode_cooldown(EntryMode.RETEST_CONFIRM)
    assert not ct.in_entry_mode_cooldown(EntryMode.PRE_BREAKOUT_SCOUT)
    clock.t = 21 * 60
    assert not ct.in_entry_mode_cooldown(EntryMode.RETEST_CONFIRM)


def test_win_does_not_trigger_cooldown(config):
    ct = CooldownTracker(config.cooldown)
    ct.record_result("BTCUSDT", EntryMode.BREAKOUT_CONFIRM, is_win=True)
    assert not ct.in_cooldown("BTCUSDT", EntryMode.BREAKOUT_CONFIRM)
