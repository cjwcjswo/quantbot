"""Retention policy + delete-protection rules (backend doc §25.2–§25.4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# event types that must never be auto-deleted (§25.3)
PROTECTED_EVENT_TYPES = frozenset(
    {"EMERGENCY_STOP", "EMERGENCY_CLOSE", "EMERGENCY_TPSL_FAILED",
     "TPSL_FAILED", "RISK_LOCKED", "ORDER_LOCKED", "KILL_SWITCH_TRIPPED"}
)

# tables whose LIVE rows may only be archived, never deleted (§25.3)
LIVE_PROTECTED_TABLES = frozenset(
    {"trades", "fills", "orders", "command_logs",
     "manual_intervention_logs", "position_protection_logs"}
)


@dataclass(frozen=True)
class TableRetention:
    keep_days: int
    archive_after_days: int


# §25.2 defaults
_DEFAULTS: dict[str, TableRetention] = {
    "trades": TableRetention(1825, 365),
    "orders": TableRetention(1825, 365),
    "fills": TableRetention(1825, 365),
    "positions": TableRetention(1825, 365),
    "command_logs": TableRetention(1825, 365),
    "daily_pnl": TableRetention(1825, 365),
    "manual_intervention_logs": TableRetention(1825, 365),
    "position_protection_logs": TableRetention(1825, 365),
    "bot_events_info": TableRetention(90, 30),
    "bot_events_warning": TableRetention(365, 180),
    "bot_events_error": TableRetention(1825, 365),
    "reconciliation_logs": TableRetention(180, 30),
    "signals": TableRetention(365, 90),
    "paper_account_snapshots": TableRetention(30, 7),
}

# §25.4 PAPER detail retention (keep_days)
_PAPER_DEFAULTS: dict[str, int] = {
    "paper_orders_keep_days": 180,
    "paper_fills_keep_days": 180,
    "paper_trades_keep_days": 365,
    "paper_events_keep_days": 90,
}


@dataclass
class RetentionPolicy:
    tables: dict[str, TableRetention] = field(default_factory=lambda: dict(_DEFAULTS))
    paper: dict[str, int] = field(default_factory=lambda: dict(_PAPER_DEFAULTS))

    def keep_days(self, table: str) -> int | None:
        tr = self.tables.get(table)
        return tr.keep_days if tr else None

    def archive_after_days(self, table: str) -> int | None:
        tr = self.tables.get(table)
        return tr.archive_after_days if tr else None

    @staticmethod
    def is_live_protected_table(table: str) -> bool:
        return table in LIVE_PROTECTED_TABLES

    @staticmethod
    def is_protected_event(event_type: str | None) -> bool:
        return (event_type or "") in PROTECTED_EVENT_TYPES

    def is_row_delete_protected(self, *, table: str, mode: str | None,
                                event_type: str | None = None) -> bool:
        """LIVE critical rows and protected event types may be archived but not deleted."""
        if self.is_protected_event(event_type):
            return True
        if mode == "LIVE" and self.is_live_protected_table(table):
            return True
        return False


def load_retention_policy(path: str | None = None) -> RetentionPolicy:
    """Load defaults, optionally overlaying ``config/retention.yaml`` if present."""
    policy = RetentionPolicy()
    candidate = Path(path or "config/retention.yaml")
    if not candidate.exists():
        return policy
    try:
        import yaml

        raw: dict[str, Any] = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return policy
    rp = raw.get("retention_policy", {})
    for table, cfg in rp.items():
        if isinstance(cfg, dict) and "keep_days" in cfg:
            policy.tables[table] = TableRetention(
                int(cfg.get("keep_days", 365)),
                int(cfg.get("archive_after_days", 30)),
            )
    pr = raw.get("paper_retention_policy", {})
    for key, val in pr.items():
        policy.paper[key] = int(val)
    return policy
