"""QuantBot Backend API (FastAPI control plane).

Reads Redis realtime state + Postgres history, validates user commands and
forwards them to the Bot Engine via the Redis command queue, and streams state
to the dashboard over WebSocket. It never touches Bybit or `apps.bot.*` directly.
"""
