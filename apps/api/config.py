"""ApiSettings: backend-specific settings from env (backend doc §6, §7)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "local"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    api_auth_enabled: bool = False
    api_token_dev: str = "dev-token"

    heartbeat_alive_sec: int = 15
    # When false the maintenance scheduler is not started (tests, or a split-out worker).
    api_run_maintenance: bool = True

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
