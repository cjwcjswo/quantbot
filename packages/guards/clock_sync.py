"""Clock-drift guard (impl doc §7 clock_sync, §16 Pre-order Check).

Tracks the offset between local time and the exchange server time. Trading is
blocked when |drift| exceeds ``block_trading_if_drift_ms_above``.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class ClockSyncGuard:
    def __init__(
        self,
        *,
        max_time_drift_ms: int = 500,
        block_trading_if_drift_ms_above: int = 1000,
    ) -> None:
        self._max_drift_ms = max_time_drift_ms
        self._block_above_ms = block_trading_if_drift_ms_above
        self._drift_ms: float = 0.0
        self._last_sync_ms: int | None = None

    @property
    def drift_ms(self) -> float:
        return self._drift_ms

    def update(self, server_time_ms: int, local_time_ms: int | None = None) -> float:
        """Record a fresh server timestamp and recompute drift.

        ``drift_ms`` is ``local - server`` (positive => local clock ahead).
        """
        local = local_time_ms if local_time_ms is not None else int(time.time() * 1000)
        self._drift_ms = float(local - server_time_ms)
        self._last_sync_ms = local
        if abs(self._drift_ms) > self._max_drift_ms:
            logger.warning("Clock drift %.0fms exceeds soft limit", self._drift_ms)
        return self._drift_ms

    def is_within_tolerance(self) -> bool:
        """True when drift is small enough to allow trading (impl doc §16)."""
        return abs(self._drift_ms) <= self._block_above_ms
