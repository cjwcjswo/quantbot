"""Domain exceptions.

The hierarchy lets callers catch broad (`QuantBotError`) or narrow categories.
`GuardRejection` / `RiskRejection` are *expected control-flow* rejections (an
order was correctly blocked) and should not be treated as system failures.
"""

from __future__ import annotations


class QuantBotError(Exception):
    """Base class for all QuantBot domain errors."""


class ConfigError(QuantBotError):
    """Invalid or missing configuration."""


class RuntimeLockError(QuantBotError):
    """Failed to acquire the single-instance runtime lock (arch doc §3.3)."""


class ExchangeError(QuantBotError):
    """Generic exchange / gateway failure."""


class RateLimitError(ExchangeError):
    """Local or remote rate limit exceeded."""


class OrderError(ExchangeError):
    """Order placement / cancellation failure."""


class OrderTimeoutError(OrderError):
    """Order create/cancel did not return in time (impl doc §17.1)."""


class PositionProtectionError(QuantBotError):
    """TP/SL could not be set or verified (impl doc §5.5)."""


class GuardRejection(QuantBotError):
    """A pre-trade guard blocked the action. Expected control flow.

    Attributes:
        reason: machine-readable reason code (e.g. ``DATA_QUALITY``).
        detail: human-readable explanation.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class RiskRejection(GuardRejection):
    """RiskManager declined the order (impl doc §13). Expected control flow."""


class DataQualityError(GuardRejection):
    """Market data failed the Data Quality Guard (impl doc §15)."""
