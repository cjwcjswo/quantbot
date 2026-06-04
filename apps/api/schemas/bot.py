"""Bot command request schemas (backend doc §10)."""

from __future__ import annotations

from pydantic import BaseModel

from packages.core.enums import BotMode


class StartReq(BaseModel):
    mode: BotMode
    live_confirm: bool = False


class StopReq(BaseModel):
    close_positions: bool = False
    cancel_open_orders: bool = True


class PauseReq(BaseModel):
    reason: str = "manual pause"


class ResumeReq(BaseModel):
    reason: str = ""
