"""
Celery tasks for asynchronous document generation.

Each task follows the same pattern:
1. Mark the ``Task`` DB record as ``running``.
2. Execute the document generation (CPU/IO-bound, may take 30–120 s).
3. Save the resulting PDF to the ``documents`` table.
4. Mark the ``Task`` record as ``completed`` (or ``failed`` on error).

Progress is reported as an integer 0–100 stored in ``Task.progress`` so the
frontend can poll ``GET /api/tasks/{task_id}`` for live updates.

Retry policy
------------
Tasks are retried up to 3 times with exponential back-off (10 s, 20 s, 40 s)
on transient failures (network errors, rate-limit responses from the LLM API).
Non-retryable errors (bad YAML, missing style …) are caught and stored in
``Task.error`` without retrying.
"""
from __future__ import annotations

import traceback
from typing import Optional

from celery import Task as CeleryTask

from app.tasks.celery_app import celery_app
from app.database import db_session
from app.schemas import Task, TaskStatus, Document, DocumentType
from app.utils.logger import logger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _update_task(task_id: str, **kwargs) -> None:
    """Update fields on the ``Task`` row identified by *task_id*."""
    with db_session() as db:
        task = db.query(Task).filter(Task.id == task_id).first()
        if task is None:
            logger.warning("_update_task: task_id={} not found", task_id)
            return
        for key, value in kwargs.items():
            setattr(task, key, value)


def _save_document(
    task_id: str,
    user_id: int,
    doc_type: str,
    filename: str,
    content: bytes,
) -> int:
    """Persist a generated PDF and return its database ID."""
    with db_session() as db:
        doc = Document(
            user_id=user_id,
            task_id=task_id,
            doc_type=doc_type,
            filename=filename,
            content=content,
        )
        db.add(doc)
        db.flush()
        doc_id = doc.id
    return doc_id


def _get_task_context(task_id: str) -> tuple[int, str, str]:
    """
    Return ``(user_id, api_key_hash, resume_content)`` for *task_id*.

    Raises
    ------
    ValueError
        If the task, user, or resume cannot be found.
    """
    from app.schemas import User
    from app.services.resume_service import get_resume

    with db_session() as db:
        task = db.query(Task).filter(Task.id == task_id).first()
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        user_id = task.user_id

        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise ValueError(f"User {user_id} not found")

        resume = get_resume(db, user_id)
        if resume is None:
            raise ValueError("No resume found for this user")

        return user_id, user.api_key_hash, resume.content


# ---------------------------------------------------------------------------
# Base task class with shared error handling
# ---------------------------------------------------------------------------

class _BaseDocumentTask(CeleryTask):
    abstract = True
    max_retries = 3
    default_retry_delay = 10  # seconds

    def on_failure(self, exc, task_id, args, kwargs, einfo):  # noqa: ANN001
        logger.error("Task {} failed: {}", task_id, exc)
        _update_task(
            task_id,
            status=TaskStatus.FAILED,
            error=str(exc),
            progress=0,
        )

    def on_retry(self, exc, task_id, args, kwargs, einfo):  # noqa: ANN001
        logger.warning("Task {} retrying due to: {}", task_id, exc)
        _update_task(task_id, status=TaskStatus.RETRYING)


# ---------------------------------------------------------------------------
# Task: generate base resume
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    base=_BaseDocumentTask,
    name="document_tasks.generate_resume",
)
def generate_resume_task(
    self,
    task_id: str,
    api_key: str,
    resume_yaml: str,
    style_name: Optional[str] = None,
) -> dict:
    """
    Celery task: generate a base (non-tailored) resume PDF.

    Parameters
    ----------
    task_id:
        The ``Task.id`` already created in the database.
    api_key:
        LLM provider API key (plain text – passed in-band for simplicity;
        in a multi-tenant deployment consider a secrets store).
    resume_yaml:
        Plain-text YAML resume content.
    style_name:
        Optional CSS style name.
    """
    logger.info("generate_resume_task started (task_id={})", task_id)
    _update_task(task_id, status=TaskStatus.RUNNING, progress=10)

    try:
        from app.services.document_service import generate_resume

        _update_task(task_id, progress=20)
        pdf_bytes = generate_resume(api_key, resume_yaml, style_name)
        _update_task(task_id, progress=80)

        # Persist the document
        with db_session() as db:
            task_row = db.query(Task).filter(Task.id == task_id).first()
            user_id = task_row.user_id if task_row else 0

        doc_id = _save_document(
            task_id=task_id,
            user_id=user_id,
            doc_type=DocumentType.RESUME,
            filename="resume_base.pdf",
            content=pdf_bytes,
        )

        _update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            result=str(doc_id),
        )
        logger.info("generate_resume_task completed (task_id={}, doc_id={})", task_id, doc_id)
        return {"doc_id": doc_id, "filename": "resume_base.pdf"}

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("generate_resume_task error (task_id={}): {}\n{}", task_id, exc, tb)
        # Retry on transient errors; give up on validation / config errors.
        if _is_retryable(exc):
            _update_task(task_id, status=TaskStatus.RETRYING)
            raise self.retry(exc=exc, countdown=self.default_retry_delay * (2 ** self.request.retries))
        _update_task(task_id, status=TaskStatus.FAILED, error=str(exc), progress=0)
        raise


# ---------------------------------------------------------------------------
# Task: generate tailored resume
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    base=_BaseDocumentTask,
    name="document_tasks.generate_tailored_resume",
)
def generate_tailored_resume_task(
    self,
    task_id: str,
    api_key: str,
    resume_yaml: str,
    job_url: str,
    style_name: Optional[str] = None,
) -> dict:
    """Celery task: generate a job-tailored resume PDF."""
    logger.info("generate_tailored_resume_task started (task_id={}, job_url={})", task_id, job_url)
    _update_task(task_id, status=TaskStatus.RUNNING, progress=10)

    try:
        from app.services.document_service import generate_tailored_resume

        _update_task(task_id, progress=20)
        pdf_bytes, suggested_name = generate_tailored_resume(api_key, resume_yaml, job_url, style_name)
        _update_task(task_id, progress=80)

        filename = f"resume_tailored_{suggested_name}.pdf"

        with db_session() as db:
            task_row = db.query(Task).filter(Task.id == task_id).first()
            user_id = task_row.user_id if task_row else 0

        doc_id = _save_document(
            task_id=task_id,
            user_id=user_id,
            doc_type=DocumentType.TAILORED_RESUME,
            filename=filename,
            content=pdf_bytes,
        )

        _update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            result=str(doc_id),
        )
        logger.info(
            "generate_tailored_resume_task completed (task_id={}, doc_id={})",
            task_id,
            doc_id,
        )
        return {"doc_id": doc_id, "filename": filename}

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error(
            "generate_tailored_resume_task error (task_id={}): {}\n{}", task_id, exc, tb
        )
        if _is_retryable(exc):
            _update_task(task_id, status=TaskStatus.RETRYING)
            raise self.retry(exc=exc, countdown=self.default_retry_delay * (2 ** self.request.retries))
        _update_task(task_id, status=TaskStatus.FAILED, error=str(exc), progress=0)
        raise


# ---------------------------------------------------------------------------
# Task: generate cover letter
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    base=_BaseDocumentTask,
    name="document_tasks.generate_cover_letter",
)
def generate_cover_letter_task(
    self,
    task_id: str,
    api_key: str,
    resume_yaml: str,
    job_url: str,
    style_name: Optional[str] = None,
) -> dict:
    """Celery task: generate a cover letter PDF."""
    logger.info("generate_cover_letter_task started (task_id={}, job_url={})", task_id, job_url)
    _update_task(task_id, status=TaskStatus.RUNNING, progress=10)

    try:
        from app.services.document_service import generate_cover_letter

        _update_task(task_id, progress=20)
        pdf_bytes, suggested_name = generate_cover_letter(api_key, resume_yaml, job_url, style_name)
        _update_task(task_id, progress=80)

        filename = f"cover_letter_{suggested_name}.pdf"

        with db_session() as db:
            task_row = db.query(Task).filter(Task.id == task_id).first()
            user_id = task_row.user_id if task_row else 0

        doc_id = _save_document(
            task_id=task_id,
            user_id=user_id,
            doc_type=DocumentType.COVER_LETTER,
            filename=filename,
            content=pdf_bytes,
        )

        _update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            result=str(doc_id),
        )
        logger.info(
            "generate_cover_letter_task completed (task_id={}, doc_id={})",
            task_id,
            doc_id,
        )
        return {"doc_id": doc_id, "filename": filename}

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error(
            "generate_cover_letter_task error (task_id={}): {}\n{}", task_id, exc, tb
        )
        if _is_retryable(exc):
            _update_task(task_id, status=TaskStatus.RETRYING)
            raise self.retry(exc=exc, countdown=self.default_retry_delay * (2 ** self.request.retries))
        _update_task(task_id, status=TaskStatus.FAILED, error=str(exc), progress=0)
        raise


# ---------------------------------------------------------------------------
# Retry classification
# ---------------------------------------------------------------------------

_RETRYABLE_SUBSTRINGS = (
    "rate limit",
    "ratelimit",
    "429",
    "timeout",
    "connection",
    "network",
    "temporarily",
    "service unavailable",
    "503",
    "502",
)


def _is_retryable(exc: Exception) -> bool:
    """Return True if *exc* looks like a transient / retryable error."""
    msg = str(exc).lower()
    return any(s in msg for s in _RETRYABLE_SUBSTRINGS)
