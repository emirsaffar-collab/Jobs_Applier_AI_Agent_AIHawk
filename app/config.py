"""
Centralised configuration management for the AIHawk application.

Settings are read from environment variables (with sensible defaults) so the
app can be configured without touching source files.  A ``Settings`` singleton
is exposed as ``app.config.settings``.
"""
import os
from pathlib import Path
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    app_name: str = "AIHawk Jobs Applier"
    app_version: str = "2.0.0"
    debug: bool = False

    # ------------------------------------------------------------------
    # Server
    # ------------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: str = "sqlite:///./aihawk.db"

    # ------------------------------------------------------------------
    # Celery / task queue
    # ------------------------------------------------------------------
    # Default: in-memory broker (no Redis required for single-user mode).
    # Override with CELERY_BROKER_URL=redis://localhost:6379/0 for production.
    celery_broker_url: str = "memory://"
    celery_result_backend: str = "db+sqlite:///./celery_results.db"

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    log_level: str = "INFO"
    log_to_file: bool = True
    log_to_console: bool = True
    log_dir: str = "log"

    # ------------------------------------------------------------------
    # Document generation
    # ------------------------------------------------------------------
    output_dir: str = "data_folder/output"
    data_folder: str = "data_folder"

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    cors_origins: list[str] = ["*"]

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    secret_key: str = "change-me-in-production"

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        return v.upper()

    @property
    def output_path(self) -> Path:
        p = Path(self.output_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def data_folder_path(self) -> Path:
        return Path(self.data_folder)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached ``Settings`` singleton."""
    return Settings()


# Convenience alias used throughout the application.
settings: Settings = get_settings()
