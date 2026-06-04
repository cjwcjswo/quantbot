"""Common response envelope (backend doc §8)."""

from __future__ import annotations

from typing import Any


def ok(data: Any = None) -> dict:
    return {"ok": True, "data": data, "error": None}


def err(code: str, message: str, details: dict | None = None) -> dict:
    return {
        "ok": False,
        "data": None,
        "error": {"code": code, "message": message, "details": details or {}},
    }
