"""Run the FastAPI server using YAML runtime settings."""

from __future__ import annotations

import uvicorn

from packages.config import load_app_config


def main() -> None:
    config = load_app_config()
    uvicorn.run(
        "apps.api.main:app",
        host=config.api.api_host,
        port=config.api.api_port,
    )


if __name__ == "__main__":
    main()
