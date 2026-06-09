"""Tests for the Global Kill Switch (impl doc §7)."""

from packages.guards import GlobalKillSwitch


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_clear_initially(config):
    ks = GlobalKillSwitch(config.global_kill_switch)
    assert ks.evaluate() is None
    assert not ks.tripped


def test_consecutive_losses_trip(config):
    ks = GlobalKillSwitch(config.global_kill_switch)  # threshold 4
    for _ in range(4):
        ks.record_trade_result(is_win=False)
    assert ks.evaluate() == "CONSECUTIVE_LOSSES"


def test_win_resets_consecutive_losses(config):
    ks = GlobalKillSwitch(config.global_kill_switch)
    for _ in range(3):
        ks.record_trade_result(is_win=False)
    ks.record_trade_result(is_win=True)
    ks.record_trade_result(is_win=False)
    assert ks.evaluate() is None


def test_order_failures_window(config):
    clock = FakeClock()
    ks = GlobalKillSwitch(config.global_kill_switch, clock=clock)  # threshold 3 in 5min
    ks.record_order_failure()
    ks.record_order_failure()
    # advance past the 5-minute window; old failures should be pruned
    clock.t = 6 * 60
    ks.record_order_failure()
    assert ks.evaluate() is None
    ks.record_order_failure()
    ks.record_order_failure()
    assert ks.evaluate() == "ORDER_FAILURES"


def test_daily_loss_trip(config):
    ks = GlobalKillSwitch(config.global_kill_switch)
    ks.update_pnl(daily_loss_percent=7.0, intraday_drawdown_percent=0.0)
    assert ks.evaluate() == "DAILY_LOSS"


def test_position_mismatch_trips_immediately(config):
    ks = GlobalKillSwitch(config.global_kill_switch)  # threshold 1
    ks.record_position_mismatch()
    assert ks.evaluate() == "POSITION_MISMATCH"


def test_latches_once_tripped(config):
    ks = GlobalKillSwitch(config.global_kill_switch)
    ks.record_position_mismatch()
    assert ks.evaluate() == "POSITION_MISMATCH"
    # even after reset of the underlying counter, the latch holds until reset()
    assert ks.evaluate() == "POSITION_MISMATCH"
    ks.reset()
    assert ks.evaluate() is None
