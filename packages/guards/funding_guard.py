"""Funding Guard (impl doc §7 funding_guard).

```
block_new_entries_before_funding_min: 10   (block within 10m of next funding)
block_if_abs_funding_rate_percent_above: 0.05
reduce_position_if_abs_funding_rate_percent_above: 0.10
```
Bybit's ``fundingRate`` is a fraction (0.0001 == 0.01%); we compare on percent.
"""

from __future__ import annotations

from decimal import Decimal

from packages.config.settings import FundingGuardSection


class FundingGuard:
    def __init__(self, config: FundingGuardSection) -> None:
        self._cfg = config

    @staticmethod
    def _percent(funding_rate: Decimal | None) -> Decimal | None:
        if funding_rate is None:
            return None
        return abs(funding_rate) * Decimal(100)

    def block_new_entry(
        self,
        *,
        now_ms: int,
        next_funding_time_ms: int | None,
        funding_rate: Decimal | None,
    ) -> str | None:
        """Return a block reason, or None if entry is allowed."""
        if not self._cfg.enabled:
            return None

        if next_funding_time_ms is not None:
            minutes_to_funding = (next_funding_time_ms - now_ms) / 60_000
            if 0 <= minutes_to_funding <= self._cfg.block_new_entries_before_funding_min:
                return "FUNDING_WINDOW"

        pct = self._percent(funding_rate)
        if pct is not None and pct >= Decimal(
            str(self._cfg.block_if_abs_funding_rate_percent_above)
        ):
            return "FUNDING_RATE_HIGH"
        return None

    def should_reduce_position(self, funding_rate: Decimal | None) -> bool:
        """Very high funding => trim exposure (impl doc §7)."""
        if not self._cfg.enabled:
            return False
        pct = self._percent(funding_rate)
        return pct is not None and pct >= Decimal(
            str(self._cfg.reduce_position_if_abs_funding_rate_percent_above)
        )
