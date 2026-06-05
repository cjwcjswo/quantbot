"""Leverage policy (impl doc §13.3).

```
Scout / Breakout / Retest caps come from risk.*_max_leverage.
High ATR, consecutive losses and daily loss derisk thresholds are YAML-tuned.
```
The effective cap is the minimum of every applicable rule, floored at min_leverage.
"""

from __future__ import annotations

import math
from decimal import Decimal

from packages.config.settings import RiskSection
from packages.core.enums import EntryMode


def max_leverage(
    *,
    entry_mode: EntryMode,
    atr_percent: Decimal | None,
    consecutive_losses: int,
    daily_loss_percent: Decimal,
    config: RiskSection,
    high_quality: bool = False,
) -> Decimal:
    mode_caps = {
        EntryMode.PRE_BREAKOUT_SCOUT: config.scout_max_leverage,
        EntryMode.BREAKOUT_CONFIRM: config.breakout_max_leverage,
        EntryMode.RETEST_CONFIRM: config.retest_max_leverage,
    }
    base = mode_caps[entry_mode]
    if high_quality:
        base = config.high_quality_max_leverage
    caps = [Decimal(base)]

    if atr_percent is not None and atr_percent > Decimal(
        str(config.high_atr_derisk_threshold_percent)
    ):
        caps.append(Decimal(config.high_atr_max_leverage))
    if consecutive_losses >= config.consecutive_loss_derisk_count:
        caps.append(Decimal(config.consecutive_loss_max_leverage))
    if daily_loss_percent >= Decimal(str(config.daily_loss_derisk_percent)):
        caps.append(Decimal(config.daily_loss_max_leverage))

    return max(Decimal(config.min_leverage), min(caps))


def choose_leverage(
    *, notional: Decimal, equity: Decimal, max_lev: Decimal, min_lev: Decimal
) -> Decimal:
    """Smallest integer leverage that supports ``notional``, clamped to the cap."""
    if equity <= 0:
        return min_lev
    needed = Decimal(math.ceil(notional / equity))
    return max(min_lev, min(needed, max_lev))
