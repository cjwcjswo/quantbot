"""Global kill switch (impl doc §7 global_kill_switch).

Aggregates failure signals over rolling time windows plus PnL-based limits.
When any threshold is breached, :meth:`evaluate` reports a trip reason; the
runtime then halts new entries (and may go EMERGENCY_STOP).
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from packages.config.settings import GlobalKillSwitchSection

_FIVE_MIN = 5 * 60
_TEN_MIN = 10 * 60


class GlobalKillSwitch:
    def __init__(
        self,
        config: GlobalKillSwitchSection,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cfg = config
        self._clock = clock
        self._order_failures: deque[float] = deque()
        self._ws_disconnects: deque[float] = deque()
        self._consecutive_losses = 0
        self._position_mismatches = 0
        self._emergency_close_failures = 0
        self._slippage_breaches = 0
        self._daily_loss_percent = 0.0
        self._intraday_drawdown_percent = 0.0
        self._tripped_reason: str | None = None

    # ---- recorders ----------------------------------------------------- #
    def record_order_failure(self) -> None:
        self._order_failures.append(self._clock())

    def record_ws_disconnect(self) -> None:
        self._ws_disconnects.append(self._clock())

    def record_position_mismatch(self) -> None:
        self._position_mismatches += 1

    def record_emergency_close_failure(self) -> None:
        self._emergency_close_failures += 1

    def record_slippage_breach(self) -> None:
        self._slippage_breaches += 1

    def record_trade_result(self, *, is_win: bool) -> None:
        self._consecutive_losses = 0 if is_win else self._consecutive_losses + 1

    def update_pnl(
        self, *, daily_loss_percent: float, intraday_drawdown_percent: float
    ) -> None:
        # daily_loss_percent is positive when losing (e.g. 5.0 == -5%).
        self._daily_loss_percent = daily_loss_percent
        self._intraday_drawdown_percent = intraday_drawdown_percent

    # ---- evaluation ---------------------------------------------------- #
    def _prune(self) -> None:
        now = self._clock()
        while self._order_failures and now - self._order_failures[0] > _FIVE_MIN:
            self._order_failures.popleft()
        while self._ws_disconnects and now - self._ws_disconnects[0] > _TEN_MIN:
            self._ws_disconnects.popleft()

    def evaluate(self) -> str | None:
        """Return a trip reason string, or None if all clear. Latches once tripped."""
        if self._tripped_reason is not None:
            return self._tripped_reason
        self._prune()
        c = self._cfg
        checks: list[tuple[bool, str]] = [
            (self._daily_loss_percent >= c.daily_loss_percent, "DAILY_LOSS"),
            (
                self._intraday_drawdown_percent >= c.intraday_drawdown_percent,
                "INTRADAY_DRAWDOWN",
            ),
            (self._consecutive_losses >= c.consecutive_losses, "CONSECUTIVE_LOSSES"),
            (
                len(self._order_failures) >= c.order_failures_in_5min,
                "ORDER_FAILURES",
            ),
            (
                len(self._ws_disconnects) >= c.websocket_disconnects_in_10min,
                "WEBSOCKET_DISCONNECTS",
            ),
            (
                self._position_mismatches >= c.unexpected_position_mismatch_count,
                "POSITION_MISMATCH",
            ),
            (
                self._emergency_close_failures >= c.emergency_close_failure_count,
                "EMERGENCY_CLOSE_FAILURE",
            ),
            (
                self._slippage_breaches >= c.max_slippage_percent_breach_count,
                "SLIPPAGE_BREACH",
            ),
        ]
        for tripped, reason in checks:
            if tripped:
                self._tripped_reason = reason
                return reason
        return None

    @property
    def tripped(self) -> bool:
        return self.evaluate() is not None

    def snapshot(self) -> dict:
        """Current counters for Redis/dashboard risk status."""
        self._prune()
        return {
            "tripped": self._tripped_reason is not None,
            "tripped_reason": self._tripped_reason,
            "daily_loss_percent": self._daily_loss_percent,
            "intraday_drawdown_percent": self._intraday_drawdown_percent,
            "consecutive_losses": self._consecutive_losses,
            "order_failures_5min": len(self._order_failures),
            "websocket_disconnects_10min": len(self._ws_disconnects),
            "position_mismatches": self._position_mismatches,
            "emergency_close_failures": self._emergency_close_failures,
            "slippage_breaches": self._slippage_breaches,
        }

    def reset(self) -> None:
        """Manual reset (operator-initiated)."""
        self.__init__(self._cfg, self._clock)
