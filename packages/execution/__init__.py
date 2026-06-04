"""Order execution: policy, LIVE OrderManager, PAPER engine (arch doc §6.20, §6.9)."""

from packages.execution.order_manager import OrderManager, OrderOutcome
from packages.execution.order_policy import (
    aggressive_limit_price,
    assert_live_new_entry_allowed,
    entry_order_type,
)
from packages.execution.paper_execution_engine import PaperExecutionEngine, PaperFill

__all__ = [
    "OrderManager",
    "OrderOutcome",
    "PaperExecutionEngine",
    "PaperFill",
    "aggressive_limit_price",
    "assert_live_new_entry_allowed",
    "entry_order_type",
]
