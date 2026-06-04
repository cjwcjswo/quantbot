"""Order request schemas (backend doc §12.2)."""

from __future__ import annotations

from pydantic import BaseModel


class CancelReq(BaseModel):
    reason: str = "manual dashboard cancel"
