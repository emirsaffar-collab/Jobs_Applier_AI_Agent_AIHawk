"""
Application configuration management.

Loads settings from environment variables (with ``AIHAWK_`` prefix),
``config.py`` at the project root, and sensible defaults.  All settings
are exposed as a single :class:`AppConfig` dataclass instance accessible
via :func:`get_config`.

Environment variables take precedence over ``config.py`` values, which in
turn take precedence over built-in defaults.

Example
-------
    from src.config import get_config

    cfg = get_config()
    print(cfg.llm_model)
    print(cfg.web_host)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    """Return the value of environment variable *AIHAWK_<KEY>* or *default*."""
    return os.environ.get(f"AIHAWK_{key.upper()}", default)


def _env_bool(key: str, default: bool = False) -> bool:
    val = _env(key)
    if val == "":
        return default
    return val.lower() in ("1", "true", "yes", "on")


def _env_int(key: str, default: int = 0) -> int:
    val = _env(key)
    if val == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# AppConfig dataclass
# ---------------------------------------------------------------------------

@dataclass
class AppConfig:
    """Immutable application configuration.

    Attributes
    ----------
    data_folder:
        Path to the user data directory (secrets, resume, preferences).
    output_folder:
        Path where generated documents are written.
    log_level:
        Minimum log level (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``).
    log_to_file:
        Whether to write logs to a rotating file.
    log_to_console:
        Whether to write logs to stderr.
    log_dir:
        Directory for log files.
    llm_model_type:
        LLM provider (``openai``, ``claude``, ``ollama``, ``gemini``, …).
    llm_model:
        Model identifier passed to the LLM provider.
    llm_api_url:
        Base URL for self-hosted LLM endpoints (Ollama, etc.).
    web_host:
        Host the FastAPI server binds to.
    web_port:
        Port the FastAPI server listens on.
    web_reload:
        Enable uvicorn auto-reload (development only).
    db_url:
        SQLAlchemy database URL.
    task_max_workers:
        Maximum number of concurrent background task workers.
    task_max_retries:
        Maximum retry attempts for failed background tasks.
    task_retry_delay:
        Seconds to wait between task retries.
    job_max_applications:
        Maximum number of job applications per run.
    job_min_applications:
        Minimum number of job applications per run.
    job_suitability_score:
        Minimum suitability score (0-10) to apply for a job.
    minimum_wait_time:
        Minimum seconds to wait between actions.
    """

    # Paths
    data_folder: Path = field(default_factory=lambda: Path("data_folder"))
    output_folder: Path = field(default_factory=lambda: Path("data_folder/output"))

    # Logging
    log_level: str = "INFO"
    log_to_file: bool = False
    log_to_console: bool = True
    log_dir: Path = field(default_factory=lambda: Path("log"))

    # LLM
    llm_model_type: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_api_url: str = ""

    # Web server
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    web_reload: bool = False

    # Database
    db_url: str = "sqlite:///aihawk.db"

    # Background tasks
    task_max_workers: int = 4
    task_max_retries: int = 3
    task_retry_delay: int = 5

    # Job application limits
    job_max_applications: int = 5
    job_min_applications: int = 1
    job_suitability_score: int = 7
    minimum_wait_time: int = 60


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def _load_root_config() -> dict:
    """Attempt to import the project-root ``config.py`` and return its attrs."""
    try:
        import config as root_cfg  # type: ignore

        return {k: getattr(root_cfg, k) for k in dir(root_cfg) if not k.startswith("_")}
    except ImportError:
        return {}


def build_config() -> AppConfig:
    """Build an :class:`AppConfig` from environment variables and ``config.py``.

    Resolution order (highest → lowest priority):
    1. ``AIHAWK_*`` environment variables
    2. Project-root ``config.py``
    3. Built-in defaults
    """
    root = _load_root_config()

    def _r(key: str, default):
        """Return value from root config or default."""
        return root.get(key, default)

    cfg = AppConfig(
        # Paths
        data_folder=Path(_env("DATA_FOLDER") or _r("DATA_FOLDER", "data_folder")),
        output_folder=Path(
            _env("OUTPUT_FOLDER") or _r("OUTPUT_FOLDER", "data_folder/output")
        ),
        # Logging
        log_level=_env("LOG_LEVEL") or _r("LOG_LEVEL", "INFO"),
        log_to_file=_env_bool("LOG_TO_FILE")
        if _env("LOG_TO_FILE")
        else bool(_r("LOG_TO_FILE", False)),
        log_to_console=_env_bool("LOG_TO_CONSOLE")
        if _env("LOG_TO_CONSOLE")
        else bool(_r("LOG_TO_CONSOLE", True)),
        log_dir=Path(_env("LOG_DIR") or _r("LOG_DIR", "log")),
        # LLM
        llm_model_type=_env("LLM_MODEL_TYPE") or _r("LLM_MODEL_TYPE", "openai"),
        llm_model=_env("LLM_MODEL") or _r("LLM_MODEL", "gpt-4o-mini"),
        llm_api_url=_env("LLM_API_URL") or _r("LLM_API_URL", ""),
        # Web server
        web_host=_env("WEB_HOST") or _r("WEB_HOST", "0.0.0.0"),
        web_port=_env_int("WEB_PORT") or int(_r("WEB_PORT", 8000)),
        web_reload=_env_bool("WEB_RELOAD")
        if _env("WEB_RELOAD")
        else bool(_r("WEB_RELOAD", False)),
        # Database
        db_url=_env("DB_URL") or _r("DB_URL", "sqlite:///aihawk.db"),
        # Background tasks
        task_max_workers=_env_int("TASK_MAX_WORKERS")
        or int(_r("TASK_MAX_WORKERS", 4)),
        task_max_retries=_env_int("TASK_MAX_RETRIES")
        or int(_r("TASK_MAX_RETRIES", 3)),
        task_retry_delay=_env_int("TASK_RETRY_DELAY")
        or int(_r("TASK_RETRY_DELAY", 5)),
        # Job application limits
        job_max_applications=_env_int("JOB_MAX_APPLICATIONS")
        or int(_r("JOB_MAX_APPLICATIONS", 5)),
        job_min_applications=_env_int("JOB_MIN_APPLICATIONS")
        or int(_r("JOB_MIN_APPLICATIONS", 1)),
        job_suitability_score=_env_int("JOB_SUITABILITY_SCORE")
        or int(_r("JOB_SUITABILITY_SCORE", 7)),
        minimum_wait_time=_env_int("MINIMUM_WAIT_TIME")
        or int(_r("MINIMUM_WAIT_TIME_IN_SECONDS", 60)),
    )
    return cfg


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Return the application-wide :class:`AppConfig` singleton.

    The config is built lazily on first access and cached for the lifetime
    of the process.
    """
    global _config
    if _config is None:
        _config = build_config()
    return _config


def reset_config() -> None:
    """Reset the cached config (useful in tests)."""
    global _config
    _config = None
