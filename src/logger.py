"""
Centralised logging configuration for the AIHawk application.

Provides a single ``get_logger`` helper that returns a loguru logger bound
with a module-specific context, plus an ``AppLogger`` class that wires up
file and console sinks according to the application configuration.

Usage
-----
    from src.logger import get_logger

    log = get_logger(__name__)
    log.info("Starting document generation")
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional

from loguru import logger as _loguru_logger

# ---------------------------------------------------------------------------
# Defaults (overridden by AppLogger.configure or config.py values)
# ---------------------------------------------------------------------------

_DEFAULT_LOG_LEVEL = "INFO"
_DEFAULT_LOG_DIR = Path("log")
_DEFAULT_ROTATION = "10 MB"
_DEFAULT_RETENTION = "1 week"
_DEFAULT_COMPRESSION = "zip"

_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)

_SIMPLE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} | {message}"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_logger(name: str = "aihawk"):
    """Return a loguru logger bound with *name* as extra context.

    Parameters
    ----------
    name:
        Typically ``__name__`` of the calling module.

    Returns
    -------
    loguru.Logger
        A logger instance with ``name`` bound as extra context so that
        structured log records carry the originating module name.
    """
    return _loguru_logger.bind(module=name)


# ---------------------------------------------------------------------------
# AppLogger – configures sinks once at startup
# ---------------------------------------------------------------------------

class AppLogger:
    """Configures loguru sinks for the application.

    Call :meth:`configure` once during application startup.  Subsequent
    calls to :func:`get_logger` will automatically use the configured sinks.

    Parameters
    ----------
    log_level:
        Minimum log level for all sinks (e.g. ``"DEBUG"``, ``"INFO"``).
    log_dir:
        Directory where rotating log files are written.
    to_file:
        Whether to write logs to a rotating file.
    to_console:
        Whether to write logs to *stderr*.
    """

    _configured: bool = False

    @classmethod
    def configure(
        cls,
        log_level: str = _DEFAULT_LOG_LEVEL,
        log_dir: Path = _DEFAULT_LOG_DIR,
        to_file: bool = True,
        to_console: bool = True,
        rotation: str = _DEFAULT_ROTATION,
        retention: str = _DEFAULT_RETENTION,
        compression: str = _DEFAULT_COMPRESSION,
    ) -> None:
        """Set up loguru sinks.  Safe to call multiple times; re-configures."""
        _loguru_logger.remove()

        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        if to_file:
            log_file = log_dir / "app.log"
            _loguru_logger.add(
                str(log_file),
                level=log_level.upper(),
                rotation=rotation,
                retention=retention,
                compression=compression,
                format=_LOG_FORMAT,
                backtrace=True,
                diagnose=True,
                enqueue=True,  # thread-safe async logging
            )

        if to_console:
            _loguru_logger.add(
                sys.stderr,
                level=log_level.upper(),
                format=_LOG_FORMAT,
                backtrace=True,
                diagnose=True,
                colorize=True,
            )

        cls._configured = True
        _loguru_logger.debug(
            "Logging configured: level={} file={} console={}",
            log_level,
            to_file,
            to_console,
        )

    @classmethod
    def configure_from_app_config(cls) -> None:
        """Read settings from ``config.py`` and call :meth:`configure`."""
        try:
            from config import LOG_LEVEL, LOG_TO_FILE, LOG_TO_CONSOLE  # type: ignore
            cls.configure(
                log_level=LOG_LEVEL,
                to_file=LOG_TO_FILE,
                to_console=LOG_TO_CONSOLE,
            )
        except ImportError:
            cls.configure()


# ---------------------------------------------------------------------------
# Intercept stdlib ``logging`` so third-party libraries route through loguru
# ---------------------------------------------------------------------------

class _InterceptHandler(logging.Handler):
    """Redirect stdlib logging records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover
        try:
            level = _loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno  # type: ignore[assignment]

        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore[assignment]
            depth += 1

        _loguru_logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def intercept_stdlib_logging(level: int = logging.DEBUG) -> None:
    """Route all stdlib ``logging`` calls through loguru.

    Call this once at startup after :meth:`AppLogger.configure`.
    """
    logging.basicConfig(handlers=[_InterceptHandler()], level=level, force=True)
    for name in logging.root.manager.loggerDict:
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


# ---------------------------------------------------------------------------
# Module-level convenience logger (used by ``from src.logger import logger``)
# ---------------------------------------------------------------------------

logger = get_logger("aihawk")
