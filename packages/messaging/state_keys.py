"""Redis key / channel names shared with the (future) Backend API (arch doc §8)."""

from __future__ import annotations

# Realtime state (StatePublisher -> Backend -> dashboard)
BOT_STATUS = "bot:status"
BOT_MODE = "bot:mode"
BOT_HEARTBEAT = "bot:heartbeat"
BOT_RISK_STATUS = "bot:risk_status"
BOT_POSITIONS = "bot:positions"
BOT_PNL = "bot:pnl"
BOT_PROTECTION_STATUS = "bot:protection_status"
BOT_RECONCILIATION_STATUS = "bot:reconciliation_status"
BOT_WATCHLIST = "bot:watchlist"  # scanner candidates + per-symbol entry preview

# Command queue (Backend -> Bot Engine) and event stream (Bot Engine -> Backend)
COMMANDS_BOT = "commands:bot"
EVENTS_BOT = "events:bot"

# Single-instance runtime lock (arch doc §3.3)
LOCK_LIVE = "lock:quantbot:live"
