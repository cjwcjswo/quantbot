"""Strategy config request schema (backend doc §15.2)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ConfigPatchReq(BaseModel):
    config_version: int
    patch: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
