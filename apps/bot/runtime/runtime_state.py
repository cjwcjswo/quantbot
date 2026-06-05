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
        self.pending_order_symbols: dict[str, str] = {}  # client_order_id -> symbol
        self.position_update_symbols: dict[str, int] = {}  # symbol -> in-flight count
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

    def open_positions(self) -> list[Position]:
        return [
            p
            for p in self.positions.values()
            if p.status in (
                PositionStatus.PENDING,
                PositionStatus.ACTIVE,
                PositionStatus.CLOSING,
            )
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
        ids.update(self.pending_order_symbols.keys())
        ids.update(self.external_orders.keys())
        return ids

    def reserve_order(self, client_order_id: str | None, symbol: str) -> None:
        if client_order_id:
            self.pending_order_symbols[client_order_id] = symbol

    def clear_order_reservation(self, client_order_id: str | None) -> None:
        if client_order_id:
            self.pending_order_symbols.pop(client_order_id, None)

    def has_pending_order_for_symbol(self, symbol: str) -> bool:
        return symbol in self.pending_order_symbols.values()

    def begin_position_update(self, symbol: str) -> None:
        self.position_update_symbols[symbol] = (
            self.position_update_symbols.get(symbol, 0) + 1
        )

    def end_position_update(self, symbol: str) -> None:
        count = self.position_update_symbols.get(symbol, 0)
        if count <= 1:
            self.position_update_symbols.pop(symbol, None)
        else:
            self.position_update_symbols[symbol] = count - 1

    def has_position_update_for_symbol(self, symbol: str) -> bool:
        return self.position_update_symbols.get(symbol, 0) > 0

    def has_bot_order_settling_for_symbol(self, symbol: str) -> bool:
        return (
            self.has_pending_order_for_symbol(symbol)
            or self.has_position_update_for_symbol(symbol)
        )

    # ---- new-entry pause window (impl doc §4.3) ------------------------ #
    def pause_new_entries(self, seconds: float) -> None:
        until = self._clock() + seconds
        self._new_entry_pause_until = max(self._new_entry_pause_until, until)

    def new_entries_paused(self) -> bool:
        return self._clock() < self._new_entry_pause_until

    def pause_remaining_sec(self) -> float:
        return max(0.0, self._new_entry_pause_until - self._clock())
