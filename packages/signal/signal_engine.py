"""SignalEngine: collect strategy signals into standard Signals (arch doc §6.17).

Runs every active strategy for a symbol, removes duplicate directions (keeping the
highest score) and returns the standard Signal list for the EntryTimingEngine.
"""

from __future__ import annotations

from packages.core.models import IndicatorSnapshot, Signal
from packages.strategy import StrategyContext, StrategyRegistry


class SignalEngine:
    def __init__(self, registry: StrategyRegistry) -> None:
        self._registry = registry

    def generate(
        self, symbol: str, snapshots: dict[str, IndicatorSnapshot]
    ) -> list[Signal]:
        ctx = StrategyContext(symbol=symbol, snapshots=snapshots)
        collected: list[Signal] = []
        for strategy in self._registry.active():
            sig = strategy.evaluate(ctx)
            if sig is not None:
                collected.append(sig)

        # De-duplicate per direction, keeping the highest score.
        best: dict[str, Signal] = {}
        for sig in collected:
            key = sig.direction.value
            if key not in best or sig.score > best[key].score:
                best[key] = sig
        return sorted(best.values(), key=lambda s: s.score, reverse=True)
