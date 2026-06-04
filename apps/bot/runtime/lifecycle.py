"""Process lifecycle helpers: signal handling and run loop."""

from __future__ import annotations

import asyncio
import logging
import signal

from apps.bot.runtime.bot_runtime import BotRuntime

logger = logging.getLogger(__name__)


def _install_signal_handlers(runtime: BotRuntime) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, runtime.request_shutdown)
        except NotImplementedError:
            # add_signal_handler is unavailable on Windows event loops.
            try:
                signal.signal(sig, lambda *_: runtime.request_shutdown())
            except (ValueError, OSError):
                pass


async def run_runtime(runtime: BotRuntime) -> None:
    """Run the runtime until a shutdown signal is received."""
    _install_signal_handlers(runtime)
    await runtime.run()
