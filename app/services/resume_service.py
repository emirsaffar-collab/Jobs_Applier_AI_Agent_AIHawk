"""
Resume management service.

Handles storing, retrieving, and validating plain-text YAML resumes in the
SQLite database.  Each logical user (identified by their hashed API key) has
at most one active resume; uploading a new one replaces the previous record.
"""
from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from app.schemas import Resume, User
from app.utils.logger import logger
from app.utils.validators import validate_resume_yaml


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hash_api_key(api_key: str) -> str:
    """Return a SHA-256 hex digest of *api_key*."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def _get_or_create_user(db: Session, api_key: str) -> User:
    """Return the ``User`` row for *api_key*, creating it if necessary."""
    key_hash = _hash_api_key(api_key)
    user = db.query(User).filter(User.api_key_hash == key_hash).first()
    if user is None:
        user = User(api_key_hash=key_hash)
        db.add(user)
        db.flush()  # populate user.id without committing
        logger.info("Created new user record (id={})", user.id)
    return user


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_user_by_api_key(db: Session, api_key: str) -> User | None:
    """Return the ``User`` row for *api_key* or ``None`` if not found."""
    key_hash = _hash_api_key(api_key)
    return db.query(User).filter(User.api_key_hash == key_hash).first()


def get_or_create_user(db: Session, api_key: str) -> User:
    """Public wrapper around ``_get_or_create_user``."""
    return _get_or_create_user(db, api_key)


def save_resume(db: Session, api_key: str, content: str) -> Resume:
    """
    Persist *content* as the active resume for the user identified by
    *api_key*.  Replaces any existing resume for that user.

    Raises
    ------
    ValueError
        If *content* fails YAML / schema validation.
    """
    valid, error = validate_resume_yaml(content)
    if not valid:
        raise ValueError(error)

    user = _get_or_create_user(db, api_key)

    # Replace existing resume if present.
    existing = (
        db.query(Resume)
        .filter(Resume.user_id == user.id)
        .order_by(Resume.created_at.desc())
        .first()
    )
    if existing:
        existing.content = content
        existing.size = len(content.encode())
        db.flush()
        logger.info("Updated resume for user_id={} (resume_id={})", user.id, existing.id)
        return existing

    resume = Resume(
        user_id=user.id,
        content=content,
        size=len(content.encode()),
    )
    db.add(resume)
    db.flush()
    logger.info("Saved new resume for user_id={} (resume_id={})", user.id, resume.id)
    return resume


def get_resume(db: Session, user_id: int) -> Resume | None:
    """Return the most recent resume for *user_id*, or ``None``."""
    return (
        db.query(Resume)
        .filter(Resume.user_id == user_id)
        .order_by(Resume.created_at.desc())
        .first()
    )


def get_resume_content(db: Session, user_id: int) -> str | None:
    """Return the raw YAML string of the most recent resume, or ``None``."""
    resume = get_resume(db, user_id)
    return resume.content if resume else None
