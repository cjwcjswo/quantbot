"""Cooldown tracking after losses (impl doc §7 cooldown).

```
symbol_cooldown_after_loss_min:      15  (after 1 loss on a symbol)
symbol_cooldown_after_2_losses_min:  60  (after 2 losses on a symbol)
global_cooldown_after_3_losses_min:  30  (3 losses across all symbols)
entry_mode_cooldown_after_loss_min:  20  (per entry mode)
```
New entries on a symbol / entry-mode / globally are blocked while in cooldown.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from packages.config.settings import CooldownSection
from packages.core.enums import EntryMode

_MIN = 60.0  # seconds per minute


class CooldownTracker:
    def __init__(
        self, config: CooldownSection, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._cfg = config
        self._clock = clock
        self._symbol_losses: dict[str, list[float]] = {}
        self._global_losses: list[float] = []
        self._entry_mode_losses: dict[EntryMode, float] = {}

    def record_result(
        self, symbol: str, entry_mode: EntryMode, *, is_win: bool
    ) -> None:
        if is_win:
            return
        now = self._clock()
        self._symbol_losses.setdefault(symbol, []).append(now)
        self._global_losses.append(now)
        self._entry_mode_losses[entry_mode] = now

    # ---- queries ------------------------------------------------------- #
    def in_symbol_cooldown(self, symbol: str) -> bool:
        losses = self._symbol_losses.get(symbol)
        if not losses:
            return False
        now = self._clock()
        last = losses[-1]
        within_60 = [t for t in losses if now - t <= self._cfg.symbol_cooldown_after_2_losses_min * _MIN]
        if len(within_60) >= 2:
            return now - last <= self._cfg.symbol_cooldown_after_2_losses_min * _MIN
        return now - last <= self._cfg.symbol_cooldown_after_loss_min * _MIN

    def in_global_cooldown(self) -> bool:
        now = self._clock()
        window = self._cfg.global_cooldown_after_3_losses_min * _MIN
        recent = [t for t in self._global_losses if now - t <= window]
        return len(recent) >= 3

    def in_entry_mode_cooldown(self, entry_mode: EntryMode) -> bool:
        last = self._entry_mode_losses.get(entry_mode)
        if last is None:
            return False
        return self._clock() - last <= self._cfg.entry_mode_cooldown_after_loss_min * _MIN

    def in_cooldown(self, symbol: str, entry_mode: EntryMode) -> bool:
        return (
            self.in_symbol_cooldown(symbol)
            or self.in_global_cooldown()
            or self.in_entry_mode_cooldown(entry_mode)
        )
