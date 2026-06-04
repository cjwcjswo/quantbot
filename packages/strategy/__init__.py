"""Strategy AddOn framework + v1 Trend Following (arch doc §3.9, §6.15-6.16)."""

from packages.strategy.base import Strategy, StrategyContext
from packages.strategy.registry import StrategyRegistry
from packages.strategy.trend_following import TrendFollowingStrategy

__all__ = [
    "Strategy",
    "StrategyContext",
    "StrategyRegistry",
    "TrendFollowingStrategy",
]
