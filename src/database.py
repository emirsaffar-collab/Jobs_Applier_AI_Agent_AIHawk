"""
SQLite database setup and session management using SQLAlchemy.

Provides:
- Declarative base for ORM models
- Engine / session factory wired to the configured DB URL
- ORM models for persisting tasks, generated documents, and user preferences
- Helper functions for common CRUD operations

Usage
-----
    from src.database import get_db, GeneratedDocument, TaskRecord

    with get_db() as db:
        doc = db.query(GeneratedDocument).filter_by(task_id=task_id).first()
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Generator, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config import get_config
from src.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Engine & session factory (initialised lazily)
# ---------------------------------------------------------------------------

_engine = None
_SessionLocal = None


def _get_engine():
    global _engine
    if _engine is None:
        cfg = get_config()
        log.debug("Creating database engine: {}", cfg.db_url)
        connect_args = {}
        if cfg.db_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False

        _engine = create_engine(
            cfg.db_url,
            connect_args=connect_args,
            echo=False,
        )

        # Enable WAL mode for SQLite to allow concurrent reads during writes
        if cfg.db_url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _set_wal(dbapi_conn, _connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

    return _engine


def _get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=_get_engine(),
            autocommit=False,
            autoflush=False,
        )
    return _SessionLocal


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------

class TaskRecord(Base):
    """Persists the state of a background document-generation task."""

    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_type = Column(String(64), nullable=False)          # e.g. "resume", "cover_letter"
    status = Column(String(32), nullable=False, default="pending")
    progress = Column(Integer, default=0)                   # 0-100
    message = Column(Text, default="")                      # human-readable status
    error = Column(Text, nullable=True)                     # error detail on failure
    retries = Column(Integer, default=0)
    job_url = Column(Text, nullable=True)
    style_name = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_type": self.task_type,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "retries": self.retries,
            "job_url": self.job_url,
            "style_name": self.style_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class GeneratedDocument(Base):
    """Stores metadata and the binary content of a generated PDF."""

    __tablename__ = "generated_documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String(36), nullable=False, index=True)
    document_type = Column(String(64), nullable=False)      # "resume" | "cover_letter"
    file_name = Column(String(256), nullable=False)
    file_path = Column(Text, nullable=True)                 # path on disk (if saved)
    file_size = Column(Integer, nullable=True)              # bytes
    style_name = Column(String(128), nullable=True)
    job_url = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "document_type": self.document_type,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "style_name": self.style_name,
            "job_url": self.job_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class UserPreference(Base):
    """Key-value store for user preferences."""

    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(128), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all tables if they do not already exist."""
    engine = _get_engine()
    log.info("Initialising database schema")
    Base.metadata.create_all(bind=engine)
    log.info("Database schema ready")


# ---------------------------------------------------------------------------
# Session context manager
# ---------------------------------------------------------------------------

@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy :class:`Session` and handle commit / rollback.

    Usage::

        with get_db() as db:
            db.add(record)
    """
    SessionLocal = _get_session_factory()
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def create_task(
    task_type: str,
    job_url: Optional[str] = None,
    style_name: Optional[str] = None,
) -> TaskRecord:
    """Create and persist a new :class:`TaskRecord` with status ``pending``."""
    record = TaskRecord(
        task_type=task_type,
        status="pending",
        progress=0,
        job_url=job_url,
        style_name=style_name,
    )
    with get_db() as db:
        db.add(record)
        db.flush()
        db.refresh(record)
        task_dict = record.to_dict()

    log.debug("Created task {}: type={}", task_dict["id"], task_type)
    return record


def update_task_progress(
    task_id: str,
    progress: int,
    message: str = "",
    status: Optional[str] = None,
) -> None:
    """Update the progress and optional status of a task."""
    with get_db() as db:
        record = db.query(TaskRecord).filter_by(id=task_id).first()
        if record is None:
            log.warning("update_task_progress: task {} not found", task_id)
            return
        record.progress = max(0, min(100, progress))
        if message:
            record.message = message
        if status:
            record.status = status
        if status == "completed":
            record.completed_at = datetime.utcnow()
    log.debug("Task {} progress={}% status={}", task_id, progress, status or "—")


def fail_task(task_id: str, error: str, increment_retries: bool = True) -> None:
    """Mark a task as failed and record the error message."""
    with get_db() as db:
        record = db.query(TaskRecord).filter_by(id=task_id).first()
        if record is None:
            log.warning("fail_task: task {} not found", task_id)
            return
        record.status = "failed"
        record.error = error
        record.completed_at = datetime.utcnow()
        if increment_retries:
            record.retries = (record.retries or 0) + 1
    log.warning("Task {} failed: {}", task_id, error)


def get_task(task_id: str) -> Optional[dict]:
    """Return a task as a plain dict, or ``None`` if not found."""
    with get_db() as db:
        record = db.query(TaskRecord).filter_by(id=task_id).first()
        return record.to_dict() if record else None


def save_document(
    task_id: str,
    document_type: str,
    file_name: str,
    file_path: Optional[str] = None,
    file_size: Optional[int] = None,
    style_name: Optional[str] = None,
    job_url: Optional[str] = None,
) -> GeneratedDocument:
    """Persist metadata for a generated document."""
    doc = GeneratedDocument(
        task_id=task_id,
        document_type=document_type,
        file_name=file_name,
        file_path=file_path,
        file_size=file_size,
        style_name=style_name,
        job_url=job_url,
    )
    with get_db() as db:
        db.add(doc)
        db.flush()
        db.refresh(doc)
        doc_dict = doc.to_dict()

    log.debug("Saved document {} for task {}", doc_dict["id"], task_id)
    return doc


def get_documents_for_task(task_id: str) -> list[dict]:
    """Return all documents associated with *task_id*."""
    with get_db() as db:
        records = (
            db.query(GeneratedDocument).filter_by(task_id=task_id).all()
        )
        return [r.to_dict() for r in records]


def set_preference(key: str, value: str) -> None:
    """Upsert a user preference."""
    with get_db() as db:
        record = db.query(UserPreference).filter_by(key=key).first()
        if record is None:
            record = UserPreference(key=key, value=value)
            db.add(record)
        else:
            record.value = value


def get_preference(key: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieve a user preference value, or *default* if absent."""
    with get_db() as db:
        record = db.query(UserPreference).filter_by(key=key).first()
        return record.value if record else default
