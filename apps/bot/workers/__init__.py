"""Async worker loops driven by BotRuntime.

Phase 3 embeds the command / reconciliation / heartbeat loops directly in
BotRuntime. Market-data, strategy, position, pnl and state-publish workers are
added in later phases.
"""
