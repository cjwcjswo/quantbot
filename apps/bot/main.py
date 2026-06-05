"""Bot Engine entry point.

The program boots to STANDBY and waits for a START command — it never starts
trading on launch (impl doc §3.2). Run with: ``uv run python -m apps.bot.main``.
"""

from __future__ import annotations

import asyncio
import logging

from apps.bot.runtime.bot_runtime import BotRuntime
from apps.bot.runtime.lifecycle import run_runtime
from packages.config import load_app_config, load_secrets
from packages.observability import setup_logging

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    path = setup_logging("bot")
    logger.info("Logging to console and %s", path)


async def _build_trade_logger(database_url: str):
    """Best-effort DB connection; PAPER can run without PostgreSQL."""
    try:
        from packages.storage import (
            TradeLogger,
            create_engine,
            init_models,
            make_session_factory,
        )

        engine = create_engine(database_url)
        await init_models(engine)
        return TradeLogger(make_session_factory(engine))
    except Exception as exc:  # noqa: BLE001
        logger.warning("DB unavailable (%s); running without persistence", exc)
        return None


async def _main() -> None:
    _configure_logging()
    secrets = load_secrets()
    config = load_app_config(secrets.quantbot_config)
    trade_logger = await _build_trade_logger(secrets.database_url)
    runtime = BotRuntime(config, secrets, trade_logger=trade_logger)
    await run_runtime(runtime)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
