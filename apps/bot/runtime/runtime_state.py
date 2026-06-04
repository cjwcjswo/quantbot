"""Shared in-memory runtime state for the Bot Engine (arch doc §6.2 RuntimeState).

Holds the internal position/order registries (compared against Bybit during
reconciliation) and the "pause new entries" window used after manual
intervention (impl doc §4.3 pause_seconds_after_external_change).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from packages.core.enums import PositionStatus
from packages.core.models import ExchangeOrder, Order, Position


class RuntimeState:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        # internal registries
        self.positions: dict[str, Position] = {}  # by symbol (bot + adopted)
        self.orders: dict[str, Order] = {}  # by client_order_id
        self.external_orders: dict[str, ExchangeOrder] = {}  # by order_id
        # new-entry pause window
        self._new_entry_pause_until: float = 0.0

    # ---- positions ----------------------------------------------------- #
    def get_position(self, symbol: str) -> Position | None:
        return self.positions.get(symbol)

    def active_bot_positions(self) -> list[Position]:
        return [
            p
            for p in self.positions.values()
            if p.is_bot_managed and p.status in (PositionStatus.ACTIVE, PositionStatus.PENDING)
        ]

    def has_open_bot_position(self) -> bool:
        return len(self.active_bot_positions()) > 0

    # ---- known order ids (for reconciliation) -------------------------- #
    def known_order_ids(self) -> set[str]:
        ids: set[str] = set()
        for o in self.orders.values():
            if o.order_id:
                ids.add(o.order_id)
            if o.client_order_id:
                ids.add(o.client_order_id)
        ids.update(self.external_orders.keys())
        return ids

    # ---- new-entry pause window (impl doc §4.3) ------------------------ #
    def pause_new_entries(self, seconds: float) -> None:
        until = self._clock() + seconds
        self._new_entry_pause_until = max(self._new_entry_pause_until, until)

    def new_entries_paused(self) -> bool:
        return self._clock() < self._new_entry_pause_until

    def pause_remaining_sec(self) -> float:
        return max(0.0, self._new_entry_pause_until - self._clock())
