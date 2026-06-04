"""Position request schemas (backend doc §11.3)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CloseReq(BaseModel):
    close_percent: float = Field(default=100, gt=0, le=100)
    reason: str = "manual dashboard close"
