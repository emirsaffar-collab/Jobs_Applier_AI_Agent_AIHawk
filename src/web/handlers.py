"""
FastAPI request handlers (route logic) for the AIHawk web API.

Handlers are kept separate from the router definitions in ``app.py`` so
they can be unit-tested without spinning up a full ASGI server.

Each handler:
- Validates inputs (Pydantic does most of this automatically).
- Delegates heavy work to :mod:`src.web.tasks` (async) or
  :mod:`src.database` (queries).
- Returns typed Pydantic response models.
- Raises :class:`fastapi.HTTPException` with structured
  :class:`~src.web.models.ErrorResponse` bodies on failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException
from fastapi.responses import FileResponse

from src.database import (
    get_documents_for_task,
    get_preference,
    get_task,
    set_preference,
)
from src.errors import RecordNotFoundError, TaskNotFoundError
from src.logger import get_logger
from src.web.models import (
    DocumentResponse,
    DocumentType,
    ErrorResponse,
    GenerateCoverLetterRequest,
    GenerateResumeRequest,
    GenerateTailoredResumeRequest,
    HealthResponse,
    PreferenceRequest,
    PreferenceResponse,
    StyleInfo,
    StyleListResponse,
    TaskResponse,
    TaskStatus,
    TaskStatusResponse,
    TaskType,
)
from src.web.tasks import task_manager

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def handle_health() -> HealthResponse:
    """Return API health status including a lightweight DB connectivity check."""
    db_status = "ok"
    try:
        from src.database import get_db, UserPreference

        with get_db() as db:
            db.query(UserPreference).limit(1).all()
    except Exception as exc:
        log.warning("Health check DB query failed: {}", exc)
        db_status = "error"

    return HealthResponse(status="ok", database=db_status)


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def handle_list_styles() -> StyleListResponse:
    """Return all available document styles discovered from the styles directory."""
    try:
        from src.libs.resume_and_cover_builder import StyleManager

        style_manager = StyleManager()
        available = style_manager.get_styles()
        styles = [
            StyleInfo(name=name, author_link=author_link, file_name=file_name)
            for name, (file_name, author_link) in available.items()
        ]
        return StyleListResponse(styles=styles, total=len(styles))
    except Exception as exc:
        log.exception("Failed to list styles: {}", exc)
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error="style_list_error",
                message="Failed to retrieve available styles.",
                details=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# Document generation
# ---------------------------------------------------------------------------

def handle_generate_resume(request: GenerateResumeRequest) -> TaskResponse:
    """Submit a plain resume generation task and return the task ID."""
    log.info("Submitting plain resume generation task (style={})", request.style_name)
    try:
        task_id = task_manager.submit_resume(style_name=request.style_name)
        return TaskResponse(
            task_id=task_id,
            task_type=TaskType.resume,
            status=TaskStatus.pending,
            message="Resume generation queued.",
        )
    except Exception as exc:
        log.exception("Failed to submit resume task: {}", exc)
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error="task_submission_error",
                message="Failed to queue resume generation task.",
                details=str(exc),
            ).model_dump(),
        )


def handle_generate_tailored_resume(
    request: GenerateTailoredResumeRequest,
) -> TaskResponse:
    """Submit a job-tailored resume generation task and return the task ID."""
    log.info(
        "Submitting tailored resume task (job_url={}, style={})",
        request.job_url,
        request.style_name,
    )
    try:
        task_id = task_manager.submit_tailored_resume(
            job_url=request.job_url, style_name=request.style_name
        )
        return TaskResponse(
            task_id=task_id,
            task_type=TaskType.resume_tailored,
            status=TaskStatus.pending,
            message="Tailored resume generation queued.",
        )
    except Exception as exc:
        log.exception("Failed to submit tailored resume task: {}", exc)
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error="task_submission_error",
                message="Failed to queue tailored resume generation task.",
                details=str(exc),
            ).model_dump(),
        )


def handle_generate_cover_letter(
    request: GenerateCoverLetterRequest,
) -> TaskResponse:
    """Submit a cover letter generation task and return the task ID."""
    log.info(
        "Submitting cover letter task (job_url={}, style={})",
        request.job_url,
        request.style_name,
    )
    try:
        task_id = task_manager.submit_cover_letter(
            job_url=request.job_url, style_name=request.style_name
        )
        return TaskResponse(
            task_id=task_id,
            task_type=TaskType.cover_letter,
            status=TaskStatus.pending,
            message="Cover letter generation queued.",
        )
    except Exception as exc:
        log.exception("Failed to submit cover letter task: {}", exc)
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error="task_submission_error",
                message="Failed to queue cover letter generation task.",
                details=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# Task status & documents
# ---------------------------------------------------------------------------

def handle_get_task_status(task_id: str) -> TaskStatusResponse:
    """Return the current status and progress of a task."""
    task = get_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="task_not_found",
                message=f"Task '{task_id}' does not exist.",
            ).model_dump(),
        )

    documents_raw = get_documents_for_task(task_id)
    documents = [
        DocumentResponse(
            id=d["id"],
            task_id=d["task_id"],
            document_type=DocumentType(d["document_type"]),
            file_name=d["file_name"],
            file_path=d.get("file_path"),
            file_size=d.get("file_size"),
            style_name=d.get("style_name"),
            job_url=d.get("job_url"),
            created_at=d.get("created_at"),
        )
        for d in documents_raw
    ]

    return TaskStatusResponse(
        task_id=task["id"],
        task_type=task["task_type"],
        status=TaskStatus(task["status"]),
        progress=task.get("progress", 0),
        message=task.get("message", ""),
        error=task.get("error"),
        retries=task.get("retries", 0),
        job_url=task.get("job_url"),
        style_name=task.get("style_name"),
        created_at=task.get("created_at"),
        updated_at=task.get("updated_at"),
        completed_at=task.get("completed_at"),
        documents=documents,
    )


def handle_list_task_documents(task_id: str) -> List[DocumentResponse]:
    """Return all documents produced by a task."""
    task = get_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="task_not_found",
                message=f"Task '{task_id}' does not exist.",
            ).model_dump(),
        )

    documents_raw = get_documents_for_task(task_id)
    return [
        DocumentResponse(
            id=d["id"],
            task_id=d["task_id"],
            document_type=DocumentType(d["document_type"]),
            file_name=d["file_name"],
            file_path=d.get("file_path"),
            file_size=d.get("file_size"),
            style_name=d.get("style_name"),
            job_url=d.get("job_url"),
            created_at=d.get("created_at"),
        )
        for d in documents_raw
    ]


def handle_download_document(task_id: str, document_id: str) -> FileResponse:
    """Stream a generated PDF document to the client."""
    from src.database import get_db, GeneratedDocument

    with get_db() as db:
        doc = (
            db.query(GeneratedDocument)
            .filter_by(id=document_id, task_id=task_id)
            .first()
        )

    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="document_not_found",
                message=f"Document '{document_id}' not found for task '{task_id}'.",
            ).model_dump(),
        )

    if not doc.file_path or not Path(doc.file_path).exists():
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="file_not_found",
                message="The document file is no longer available on disk.",
            ).model_dump(),
        )

    return FileResponse(
        path=doc.file_path,
        media_type="application/pdf",
        filename=doc.file_name,
    )


# ---------------------------------------------------------------------------
# User preferences
# ---------------------------------------------------------------------------

def handle_set_preference(request: PreferenceRequest) -> PreferenceResponse:
    """Persist a user preference key-value pair."""
    try:
        set_preference(request.key, request.value)
        log.debug("Preference set: {}={}", request.key, request.value)
        return PreferenceResponse(key=request.key, value=request.value)
    except Exception as exc:
        log.exception("Failed to set preference {}: {}", request.key, exc)
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error="preference_error",
                message="Failed to save preference.",
                details=str(exc),
            ).model_dump(),
        )


def handle_get_preference(key: str) -> PreferenceResponse:
    """Retrieve a user preference by key."""
    value = get_preference(key)
    if value is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="preference_not_found",
                message=f"Preference '{key}' has not been set.",
            ).model_dump(),
        )
    return PreferenceResponse(key=key, value=value)
