"""UniverseManager: the set of tradable instruments (arch doc §6.10).

Loads USDT-perp instruments, drops delisted / non-trading / too-new symbols and
the configured exclude list, and caches SymbolMeta. It does NOT make entry
decisions (that is SymbolScanner + strategy).
"""

from __future__ import annotations

import logging
import time

from packages.config.settings import UniverseSection
from packages.core.models import SymbolMeta
from packages.exchange import ExchangeGateway

logger = logging.getLogger(__name__)

_DAY_MS = 24 * 60 * 60 * 1000


class UniverseManager:
    def __init__(
        self,
        gateway: ExchangeGateway,
        config: UniverseSection,
        *,
        now_ms: int | None = None,
    ) -> None:
        self._gw = gateway
        self._cfg = config
        self._now_ms = now_ms
        self._symbols: dict[str, SymbolMeta] = {}

    async def refresh(self) -> None:
        instruments = await self._gw.load_instruments()
        now = self._now_ms if self._now_ms is not None else int(time.time() * 1000)
        kept: dict[str, SymbolMeta] = {}
        for meta in instruments:
            if not self._is_eligible(meta, now):
                continue
            kept[meta.symbol] = meta
        # explicit include list overrides filters (still must exist in instruments)
        for sym in self._cfg.include_symbols:
            if sym not in kept:
                match = next((m for m in instruments if m.symbol == sym), None)
                if match is not None:
                    kept[sym] = match
        self._symbols = kept
        logger.info("Universe refreshed: %d tradable symbols", len(kept))

    def _is_eligible(self, meta: SymbolMeta, now_ms: int) -> bool:
        if meta.quote_coin != self._cfg.include_quote_coin:
            return False
        if meta.status != "Trading":
            return False
        if meta.symbol in self._cfg.exclude_symbols:
            return False
        if meta.launch_time_ms is not None and self._cfg.exclude_new_listing_days > 0:
            age_days = (now_ms - meta.launch_time_ms) / _DAY_MS
            if age_days < self._cfg.exclude_new_listing_days:
                return False
        return True

    def get(self, symbol: str) -> SymbolMeta | None:
        return self._symbols.get(symbol)

    def all_symbols(self) -> list[str]:
        return list(self._symbols.keys())

    def all_meta(self) -> list[SymbolMeta]:
        return list(self._symbols.values())

    def is_tradable(self, symbol: str) -> bool:
        return symbol in self._symbols
