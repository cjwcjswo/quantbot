"""Strategy config get/patch (backend doc §15). Validation only; bot applies it."""

from __future__ import annotations

from typing import Any

from apps.api import errors
from apps.api.errors import ErrorCode
from apps.api.repositories import config_repository, position_repository
from apps.api.services import command_service
from packages.messaging import CommandType, state_keys

CONFIG_SECTIONS = (
    "bot", "paper", "universe", "scanner", "trend_quality", "volume",
    "candle_quality", "entry", "orders", "risk", "liquidation_guard",
    "tpsl", "position_protection", "position", "stagnation_exit",
    "cooldown", "global_kill_switch", "reconciliation",
    "manual_intervention", "data_quality", "funding_guard",
)
ALLOWED_TOP = {*CONFIG_SECTIONS, "strategy", "leverage", "stop_loss"}
# patches touching these are blocked while a position is open (§15.2)
RISK_TOP = {"risk", "leverage", "stop_loss", "tpsl", "position_protection"}
RISK_SUBKEY_HINTS = ("leverage", "stop_loss", "account_risk")


def _touches_risk(patch: dict) -> bool:
    for key, val in patch.items():
        if key in RISK_TOP:
            if key != "risk":
                return True
            if isinstance(val, dict) and any(
                any(h in sub for h in RISK_SUBKEY_HINTS) for sub in val
            ):
                return True
            if key == "risk":
                return True
    return False


def _section(config: Any, name: str) -> dict:
    section = getattr(config, name, None)
    if section is None:
        return {}
    dump = getattr(section, "model_dump", None)
    return dump(mode="json") if dump else {}


def _strategy_config_response(
    *, version: int, mode: str | None, stored: dict, config: Any
) -> dict:
    data = {
        "config_version": version,
        "mode": mode,
        "strategy": stored.get(
            "strategy", {"active_strategies": ["trend_following"]}
        ),
    }
    for section in CONFIG_SECTIONS:
        data[section] = stored.get(section, _section(config, section))
    return data


async def get_config(session_factory: Any, redis: Any, config: Any = None) -> dict:
    row = await config_repository.latest(session_factory)
    try:
        mode = await redis.get(state_keys.BOT_MODE)
    except Exception:  # noqa: BLE001
        mode = None
    if row is None:
        # No persisted override yet: reflect the running config (quantbot.yaml).
        return _strategy_config_response(version=0, mode=mode, stored={}, config=config)
    cfg = row.config or {}
    return _strategy_config_response(
        version=row.version, mode=row.mode or mode, stored=cfg, config=config)


async def patch_config(
    session_factory: Any, redis: Any, command_queue: Any, *,
    config_version: int, patch: dict, reason: str,
) -> dict:
    row = await config_repository.latest(session_factory)
    current_version = row.version if row else 0
    if config_version != current_version:
        raise errors.conflict(
            "config_version mismatch.",
            expected=current_version, received=config_version)

    unknown = [k for k in patch if k not in ALLOWED_TOP]
    if unknown:
        raise errors.ApiError(
            ErrorCode.VALIDATION_ERROR,
            f"Unknown config fields: {unknown}", details={"fields": unknown})

    open_positions = await position_repository.list_open(session_factory)
    if open_positions and _touches_risk(patch):
        raise errors.forbidden(
            "Risk/leverage/stop changes are not allowed while a position is open.")

    base = dict(row.config) if (row and row.config) else {}
    for key, val in patch.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            merged = dict(base[key])
            merged.update(val)
            base[key] = merged
        else:
            base[key] = val

    try:
        mode = await redis.get(state_keys.BOT_MODE)
    except Exception:  # noqa: BLE001
        mode = None
    new_version = current_version + 1
    await config_repository.insert_version(
        session_factory, name="active", config=base, version=new_version, mode=mode)

    result = await command_service.dispatch(
        session_factory=session_factory, command_queue=command_queue,
        type=CommandType.RELOAD_CONFIG,
        payload={"config_version": new_version, "reason": reason})
    return {"config_version": new_version, **result}
