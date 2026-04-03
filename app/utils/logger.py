"""
Structured logging setup for the AIHawk application.
Provides separate loggers for API, tasks, and services with configurable
log levels, file rotation, and console output.
"""
import logging
import logging.handlers
import os
import sys
from pathlib import Path

from loguru import logger  # noqa: F401  – re-exported for convenience


# ---------------------------------------------------------------------------
# Internal stdlib logger used by non-loguru modules (SQLAlchemy, uvicorn …)
# ---------------------------------------------------------------------------

def _ensure_log_dir(path: str = "log") -> Path:
    log_dir = Path(path)
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def configure_logging(
    log_level: str = "INFO",
    log_to_file: bool = True,
    log_to_console: bool = True,
    log_dir: str = "log",
) -> None:
    """
    Configure loguru with file + console sinks and a stdlib bridge so that
    third-party libraries that use the standard ``logging`` module are also
    captured.

    Call this once at application start-up (``app/main.py`` or the CLI entry
    point).
    """
    log_path = _ensure_log_dir(log_dir)

    # Remove any previously registered sinks so this function is idempotent.
    logger.remove()

    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    if log_to_console:
        logger.add(
            sys.stderr,
            level=log_level.upper(),
            format=fmt,
            backtrace=True,
            diagnose=False,  # avoid leaking secrets in tracebacks
        )

    if log_to_file:
        # General application log
        logger.add(
            log_path / "app.log",
            level=log_level.upper(),
            rotation="10 MB",
            retention="1 week",
            compression="zip",
            format=fmt,
            backtrace=True,
            diagnose=False,
        )
        # Dedicated error log – always at ERROR level regardless of global level
        logger.add(
            log_path / "errors.log",
            level="ERROR",
            rotation="10 MB",
            retention="2 weeks",
            compression="zip",
            format=fmt,
            backtrace=True,
            diagnose=False,
        )

    # Bridge stdlib logging → loguru so uvicorn / SQLAlchemy logs are captured
    class _InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno  # type: ignore[assignment]
            frame, depth = logging.currentframe(), 2
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back  # type: ignore[assignment]
                depth += 1
            logger.opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )

    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(name).handlers = [_InterceptHandler()]
        logging.getLogger(name).propagate = False
