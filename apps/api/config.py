"""ApiSettings: backend-specific runtime settings."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSecrets(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    api_token_dev: str = "dev-token"


class ApiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_env: str = "local"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    api_auth_enabled: bool = False
    api_token_dev: str = "dev-token"

    heartbeat_alive_sec: int = 15
    # When false the maintenance scheduler is not started (tests, or a split-out worker).
    api_run_maintenance: bool = True

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins if o.strip()]


def api_settings_from_config(config, secrets: ApiSecrets | None = None) -> ApiSettings:
    api = config.api
    api_secrets = secrets or ApiSecrets()
    return ApiSettings(
        app_env=api.app_env,
        api_host=api.api_host,
        api_port=api.api_port,
        cors_origins=api.cors_origins,
        api_auth_enabled=api.api_auth_enabled,
        api_token_dev=api_secrets.api_token_dev,
        heartbeat_alive_sec=api.heartbeat_alive_sec,
        api_run_maintenance=api.api_run_maintenance,
    )
