"""Funding Guard (impl doc §7 funding_guard).

```
block_new_entries_before_funding_min: 5   (block within 5m of next funding)
block_if_abs_funding_rate_percent_above: 0.08
reduce_position_if_abs_funding_rate_percent_above: 0.12
```
Bybit's ``fundingRate`` is a fraction (0.0001 == 0.01%). Positive funding is
unfavorable for longs and favorable for shorts; negative funding is the inverse.
"""

from __future__ import annotations

from decimal import Decimal

from packages.config.settings import FundingGuardSection
from packages.core.enums import PositionSide, SignalDirection


class FundingGuard:
    def __init__(self, config: FundingGuardSection) -> None:
        self._cfg = config

    @staticmethod
    def _percent(funding_rate: Decimal | None) -> Decimal | None:
        if funding_rate is None:
            return None
        return abs(funding_rate) * Decimal(100)

    @staticmethod
    def _is_unfavorable(
        funding_rate: Decimal | None,
        direction: SignalDirection | PositionSide | None,
    ) -> bool:
        if funding_rate is None:
            return False
        if direction in (SignalDirection.LONG, PositionSide.LONG):
            return funding_rate > 0
        if direction in (SignalDirection.SHORT, PositionSide.SHORT):
            return funding_rate < 0
        return True

    def block_new_entry(
        self,
        *,
        now_ms: int,
        next_funding_time_ms: int | None,
        funding_rate: Decimal | None,
        direction: SignalDirection | None = None,
    ) -> str | None:
        """Return a block reason, or None if entry is allowed."""
        if not self._cfg.enabled:
            return None

        if next_funding_time_ms is not None:
            minutes_to_funding = (next_funding_time_ms - now_ms) / 60_000
            if 0 <= minutes_to_funding <= self._cfg.block_new_entries_before_funding_min:
                return "FUNDING_WINDOW"

        pct = self._percent(funding_rate)
        if (
            pct is not None
            and pct >= Decimal(str(self._cfg.block_if_abs_funding_rate_percent_above))
            and self._is_unfavorable(funding_rate, direction)
        ):
            return "FUNDING_RATE_HIGH"
        return None

    def should_reduce_position(
        self,
        funding_rate: Decimal | None,
        side: PositionSide | None = None,
    ) -> bool:
        """Very high funding => trim exposure (impl doc §7)."""
        if not self._cfg.enabled:
            return False
        pct = self._percent(funding_rate)
        return (
            pct is not None
            and pct >= Decimal(str(self._cfg.reduce_position_if_abs_funding_rate_percent_above))
            and self._is_unfavorable(funding_rate, side)
        )
