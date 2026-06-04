"""Shared logging setup: console + rotating file handlers.

Both the Bot Engine (apps/bot) and Backend API (apps/api) call ``setup_logging``
so every runtime log is written to ``logs/<service>.log`` (size-rotated) in
addition to the console. This lets us inspect abnormal behavior after the fact
even when the console scrollback is gone.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
_MAX_BYTES = 10 * 1024 * 1024  # rotate at 10 MB
_BACKUP_COUNT = 5  # keep 5 rotated files (~50 MB/service)

__all__ = ["setup_logging"]


def setup_logging(
    service: str,
    *,
    level: int = logging.INFO,
    log_dir: str | os.PathLike[str] | None = None,
    capture_uvicorn: bool = False,
) -> Path:
    """Configure root logging with a console handler and a rotating file handler.

    Idempotent per service: calling twice for the same service is a no-op so we
    never attach duplicate handlers. ``log_dir`` defaults to ``$LOG_DIR`` or
    ``logs/`` under the current working directory (the dev scripts run from the
    repo root, and ``logs/`` is gitignored).

    Returns the path of the log file.
    """
    base = Path(log_dir or os.environ.get("LOG_DIR", "logs"))
    base.mkdir(parents=True, exist_ok=True)
    file_path = base / f"{service}.log"

    root = logging.getLogger()
    root.setLevel(level)
    if getattr(root, "_quantbot_logging", None) == service:
        return file_path

    formatter = logging.Formatter(_LOG_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        file_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if capture_uvicorn:
        # uvicorn's own loggers don't propagate to root, so attach the same file
        # handler instance to persist startup/error/access lines too.
        for name in ("uvicorn", "uvicorn.access"):
            logging.getLogger(name).addHandler(file_handler)

    root._quantbot_logging = service  # type: ignore[attr-defined]  # idempotency marker
    return file_path
