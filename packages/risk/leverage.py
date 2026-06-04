"""Leverage policy (impl doc §13.3).

```
Scout    max 3x
Breakout max 5x
Retest   max 6x
high-quality cumulative max 8x
ATR% > 3.5            => max 3x
consecutive losses>=2 => max 3x
daily loss <= -3%     => max 2x (or stop new entries)
```
The effective cap is the minimum of every applicable rule, floored at min_leverage.
"""

from __future__ import annotations

import math
from decimal import Decimal

from packages.config.settings import RiskSection
from packages.core.enums import EntryMode

_HIGH_ATR_THRESHOLD = Decimal("3.5")
_DAILY_LOSS_DERISK_PERCENT = Decimal("3.0")
_CONSECUTIVE_LOSS_DERISK = 2


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

    if atr_percent is not None and atr_percent > _HIGH_ATR_THRESHOLD:
        caps.append(Decimal(config.high_atr_max_leverage))
    if consecutive_losses >= _CONSECUTIVE_LOSS_DERISK:
        caps.append(Decimal(3))
    if daily_loss_percent >= _DAILY_LOSS_DERISK_PERCENT:
        caps.append(Decimal(2))

    return max(Decimal(config.min_leverage), min(caps))


def choose_leverage(
    *, notional: Decimal, equity: Decimal, max_lev: Decimal, min_lev: Decimal
) -> Decimal:
    """Smallest integer leverage that supports ``notional``, clamped to the cap."""
    if equity <= 0:
        return min_lev
    needed = Decimal(math.ceil(notional / equity))
    return max(min_lev, min(needed, max_lev))
