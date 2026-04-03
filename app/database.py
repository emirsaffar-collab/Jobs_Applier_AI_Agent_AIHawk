"""
SQLite database setup using SQLAlchemy.

Provides:
- Engine and session factory
- ``Base`` declarative base for ORM models
- ``init_db()`` to create all tables on startup
- ``get_db()`` FastAPI dependency for request-scoped sessions
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings
from app.utils.logger import logger


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_connect_args: dict = {}
if settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    # Keep a small pool; SQLite doesn't benefit from large pools.
    pool_pre_ping=True,
    echo=settings.debug,
)

# Enable WAL mode for SQLite so reads don't block writes.
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all tables defined in ``app.schemas`` (imported for side-effects)."""
    # Import schemas so SQLAlchemy registers the ORM models before ``create_all``.
    import app.schemas  # noqa: F401

    logger.info("Initialising database at {}", settings.database_url)
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created / verified.")


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session and ensures it is
    closed after the request completes.

    Usage::

        @router.get("/example")
        def example(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """
    Context-manager version of ``get_db`` for use outside of FastAPI
    (e.g. Celery tasks, CLI commands).

    Usage::

        with db_session() as db:
            db.add(some_model)
            db.commit()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
