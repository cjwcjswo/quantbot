"""StrategyRegistry: active strategies (arch doc §6.15).

v1 registers only TrendFollowingStrategy; further strategies can be added as
AddOns without touching the engine.
"""

from __future__ import annotations

from packages.strategy.base import Strategy


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: list[Strategy] = []

    def register(self, strategy: Strategy) -> None:
        self._strategies.append(strategy)

    def active(self) -> list[Strategy]:
        return list(self._strategies)

    def required_timeframes(self) -> set[str]:
        tfs: set[str] = set()
        for strat in self._strategies:
            tfs.update(strat.required_timeframes())
        return tfs
