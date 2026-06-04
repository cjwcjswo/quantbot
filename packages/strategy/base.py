"""Strategy interface (arch doc §6.16, §3.9 AddOn structure).

A strategy only evaluates conditions and emits candidate Signals. It does NOT
order, size, approve risk, or call the exchange (arch doc §3.9).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from packages.core.models import IndicatorSnapshot, Signal


@dataclass
class StrategyContext:
    """Per-symbol indicator snapshots keyed by timeframe ('1', '5', '15')."""

    symbol: str
    snapshots: dict[str, IndicatorSnapshot] = field(default_factory=dict)

    def get(self, timeframe: str) -> IndicatorSnapshot | None:
        return self.snapshots.get(timeframe)


class Strategy(ABC):
    name: str = "base"

    @abstractmethod
    def required_timeframes(self) -> list[str]:
        """Timeframes this strategy needs (e.g. ['5', '15'])."""

    @abstractmethod
    def evaluate(self, ctx: StrategyContext) -> Signal | None:
        """Return a candidate Signal, or None if no setup."""
