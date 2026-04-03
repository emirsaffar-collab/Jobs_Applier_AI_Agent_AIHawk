"""
FastAPI API routes.

All endpoints are mounted under the ``/api`` prefix (configured in
``app/main.py``).

Authentication
--------------
The API key is passed in the ``X-API-Key`` request header for every endpoint
that requires it.  The key is hashed before being stored; the plain-text key
is only used in-memory during the request lifetime.

Endpoints
---------
POST   /api/setup                       – configure API key (+ optional resume)
POST   /api/resume                      – upload / replace resume
GET    /api/resume/download             – download current resume as YAML
POST   /api/preferences                 – save job preferences
GET    /api/preferences                 – retrieve current preferences
POST   /api/generate                    – start async document generation
GET    /api/tasks/{task_id}             – poll task status / progress
GET    /api/documents                   – list generated documents
GET    /api/documents/{doc_id}/download – download a generated PDF
GET    /api/status                      – setup / readiness status
GET    /api/styles                      – list available CSS styles
GET    /api/health                      – health check (no auth required)
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, UploadFile, File, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    DocumentInfo,
    DocumentListResponse,
    GenerateRequest,
    GenerateResponse,
    MessageResponse,
    PreferencesRequest,
    PreferencesResponse,
    ResumeInfo,
    ResumeUploadResponse,
    SetupRequest,
    SetupResponse,
    StatusResponse,
    TaskStatusResponse,
)
from app.schemas import Document, Task, TaskStatus
from app.services.preferences_service import get_preferences, save_preferences
from app.services.resume_service import (
    get_or_create_user,
    get_resume,
    get_resume_content,
    get_user_by_api_key,
    save_resume,
)
from app.api.errors import (
    NotConfiguredError,
    ResourceNotFoundError,
    TaskNotFoundError,
    ValidationError_,
)
from app.config import settings
from app.utils.logger import logger
from app.utils.validators import validate_api_key

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency: resolve user from X-API-Key header
# ---------------------------------------------------------------------------

def _require_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
) -> str:
    """FastAPI dependency – validate and return the raw API key."""
    if not validate_api_key(x_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )
    return x_api_key


def _require_user(
    api_key: str = Depends(_require_api_key),
    db: Session = Depends(get_db),
):
    """FastAPI dependency – return the User ORM object (creates if absent)."""
    return get_or_create_user(db, api_key)


# ---------------------------------------------------------------------------
# Health check (no auth)
# ---------------------------------------------------------------------------

@router.get("/health", tags=["system"])
def health_check():
    """Simple liveness probe – always returns 200."""
    return {"status": "ok", "version": settings.app_version}


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

@router.post("/setup", response_model=SetupResponse, tags=["setup"])
def setup(
    body: SetupRequest,
    db: Session = Depends(get_db),
):
    """
    Configure the application with an LLM API key and optionally upload a
    resume in the same request.
    """
    if not validate_api_key(body.api_key):
        raise ValidationError_("The provided API key does not appear to be valid.")

    try:
        user = get_or_create_user(db, body.api_key)

        if body.resume_content:
            save_resume(db, body.api_key, body.resume_content)

        db.commit()
        logger.info("Setup completed for user_id={}", user.id)
        return SetupResponse(
            success=True,
            message="Setup completed successfully.",
            user_id=user.id,
        )
    except ValueError as exc:
        db.rollback()
        raise ValidationError_(str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Setup failed: {}", exc)
        raise


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

@router.post("/resume", response_model=ResumeUploadResponse, tags=["resume"])
async def upload_resume(
    file: UploadFile = File(...),
    api_key: str = Depends(_require_api_key),
    db: Session = Depends(get_db),
):
    """Upload a plain-text YAML resume file (replaces any existing resume)."""
    raw = await file.read()
    if len(raw) > 512 * 1024:
        raise ValidationError_("Resume file exceeds the 512 KB size limit.")

    content = raw.decode("utf-8", errors="replace")

    try:
        resume = save_resume(db, api_key, content)
        db.commit()
        return ResumeUploadResponse(
            success=True,
            message="Resume uploaded successfully.",
            resume_id=resume.id,
            size=resume.size,
        )
    except ValueError as exc:
        db.rollback()
        raise ValidationError_(str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Resume upload failed: {}", exc)
        raise


@router.get("/resume/download", tags=["resume"])
def download_resume(
    api_key: str = Depends(_require_api_key),
    db: Session = Depends(get_db),
):
    """Download the current resume as a YAML file."""
    user = get_user_by_api_key(db, api_key)
    if user is None:
        raise NotConfiguredError("No user found for this API key. Please run /api/setup first.")

    content = get_resume_content(db, user.id)
    if content is None:
        raise ResourceNotFoundError("No resume has been uploaded yet.")

    return Response(
        content=content.encode(),
        media_type="application/x-yaml",
        headers={"Content-Disposition": "attachment; filename=plain_text_resume.yaml"},
    )


@router.get("/resume", response_model=ResumeInfo, tags=["resume"])
def get_resume_info(
    api_key: str = Depends(_require_api_key),
    db: Session = Depends(get_db),
):
    """Return metadata about the currently stored resume."""
    user = get_user_by_api_key(db, api_key)
    if user is None:
        raise NotConfiguredError("No user found for this API key.")

    resume = get_resume(db, user.id)
    if resume is None:
        raise ResourceNotFoundError("No resume has been uploaded yet.")

    return ResumeInfo.model_validate(resume)


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

@router.post("/preferences", response_model=PreferencesResponse, tags=["preferences"])
def save_prefs(
    body: PreferencesRequest,
    api_key: str = Depends(_require_api_key),
    db: Session = Depends(get_db),
):
    """Save job-search preferences."""
    try:
        pref = save_preferences(db, api_key, body.model_dump())
        db.commit()
        return PreferencesResponse(
            success=True,
            message="Preferences saved.",
            preference_id=pref.id,
        )
    except ValueError as exc:
        db.rollback()
        raise ValidationError_(str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to save preferences: {}", exc)
        raise


@router.get("/preferences", tags=["preferences"])
def get_prefs(
    api_key: str = Depends(_require_api_key),
    db: Session = Depends(get_db),
):
    """Retrieve the current job-search preferences."""
    user = get_user_by_api_key(db, api_key)
    if user is None:
        raise NotConfiguredError("No user found for this API key.")

    prefs = get_preferences(db, user.id)
    if prefs is None:
        raise ResourceNotFoundError("No preferences have been saved yet.")

    return prefs


# ---------------------------------------------------------------------------
# Document generation
# ---------------------------------------------------------------------------

@router.post("/generate", response_model=GenerateResponse, tags=["generation"])
def start_generation(
    body: GenerateRequest,
    api_key: str = Depends(_require_api_key),
    db: Session = Depends(get_db),
):
    """
    Queue an async document generation task.

    Returns a ``task_id`` that can be polled via ``GET /api/tasks/{task_id}``.
    """
    from app.tasks.document_tasks import (
        generate_resume_task,
        generate_tailored_resume_task,
        generate_cover_letter_task,
    )

    user = get_user_by_api_key(db, api_key)
    if user is None:
        raise NotConfiguredError("Please run /api/setup first.")

    resume_content = get_resume_content(db, user.id)
    if resume_content is None:
        raise NotConfiguredError("Please upload a resume before generating documents.")

    if body.doc_type in ("tailored_resume", "cover_letter") and not body.job_url:
        raise ValidationError_(f"'job_url' is required for doc_type='{body.doc_type}'.")

    task_id = str(uuid.uuid4())

    # Create the task record in the database *before* queuing the Celery task
    # so the frontend can start polling immediately.
    task_row = Task(
        id=task_id,
        user_id=user.id,
        task_type=body.doc_type,
        status=TaskStatus.PENDING,
        progress=0,
    )
    db.add(task_row)
    db.commit()

    # Dispatch the appropriate Celery task.
    if body.doc_type == "resume":
        generate_resume_task.apply_async(
            kwargs={
                "task_id": task_id,
                "api_key": api_key,
                "resume_yaml": resume_content,
                "style_name": body.style,
            },
            task_id=task_id,
        )
    elif body.doc_type == "tailored_resume":
        generate_tailored_resume_task.apply_async(
            kwargs={
                "task_id": task_id,
                "api_key": api_key,
                "resume_yaml": resume_content,
                "job_url": body.job_url,
                "style_name": body.style,
            },
            task_id=task_id,
        )
    else:  # cover_letter
        generate_cover_letter_task.apply_async(
            kwargs={
                "task_id": task_id,
                "api_key": api_key,
                "resume_yaml": resume_content,
                "job_url": body.job_url,
                "style_name": body.style,
            },
            task_id=task_id,
        )

    logger.info(
        "Queued {} task (task_id={}, user_id={})",
        body.doc_type,
        task_id,
        user.id,
    )
    return GenerateResponse(
        success=True,
        task_id=task_id,
        message=f"Document generation started. Poll /api/tasks/{task_id} for progress.",
    )


# ---------------------------------------------------------------------------
# Task status
# ---------------------------------------------------------------------------

@router.get("/tasks/{task_id}", response_model=TaskStatusResponse, tags=["tasks"])
def get_task_status(
    task_id: str,
    api_key: str = Depends(_require_api_key),
    db: Session = Depends(get_db),
):
    """Poll the status and progress of a document generation task."""
    user = get_user_by_api_key(db, api_key)
    if user is None:
        raise NotConfiguredError("No user found for this API key.")

    task = (
        db.query(Task)
        .filter(Task.id == task_id, Task.user_id == user.id)
        .first()
    )
    if task is None:
        raise TaskNotFoundError(f"Task '{task_id}' not found.")

    # Resolve document_id from the result field if completed.
    document_id: Optional[int] = None
    if task.status == TaskStatus.COMPLETED and task.result:
        try:
            document_id = int(task.result)
        except (ValueError, TypeError):
            pass

    return TaskStatusResponse(
        task_id=task.id,
        status=task.status,
        progress=task.progress,
        task_type=task.task_type,
        error=task.error,
        document_id=document_id,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

@router.get("/documents", response_model=DocumentListResponse, tags=["documents"])
def list_documents(
    api_key: str = Depends(_require_api_key),
    db: Session = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
):
    """List all generated documents for the authenticated user."""
    user = get_user_by_api_key(db, api_key)
    if user is None:
        raise NotConfiguredError("No user found for this API key.")

    docs = (
        db.query(Document)
        .filter(Document.user_id == user.id)
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    total = db.query(Document).filter(Document.user_id == user.id).count()

    return DocumentListResponse(
        documents=[
            DocumentInfo(
                id=d.id,
                doc_type=d.doc_type,
                filename=d.filename,
                created_at=d.created_at,
                task_id=d.task_id,
            )
            for d in docs
        ],
        total=total,
    )


@router.get("/documents/{doc_id}/download", tags=["documents"])
def download_document(
    doc_id: int,
    api_key: str = Depends(_require_api_key),
    db: Session = Depends(get_db),
):
    """Download a generated PDF document."""
    user = get_user_by_api_key(db, api_key)
    if user is None:
        raise NotConfiguredError("No user found for this API key.")

    doc = (
        db.query(Document)
        .filter(Document.id == doc_id, Document.user_id == user.id)
        .first()
    )
    if doc is None:
        raise ResourceNotFoundError(f"Document {doc_id} not found.")

    return Response(
        content=doc.content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{doc.filename}"',
            "Content-Length": str(len(doc.content)),
        },
    )


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get("/status", response_model=StatusResponse, tags=["system"])
def get_status(
    api_key: str = Depends(_require_api_key),
    db: Session = Depends(get_db),
):
    """Return the setup / readiness status for the authenticated user."""
    user = get_user_by_api_key(db, api_key)
    has_api_key = user is not None
    has_resume = False
    has_preferences = False

    if user:
        has_resume = get_resume(db, user.id) is not None
        has_preferences = get_preferences(db, user.id) is not None

    return StatusResponse(
        has_api_key=has_api_key,
        has_resume=has_resume,
        has_preferences=has_preferences,
        app_version=settings.app_version,
        ready=has_api_key and has_resume,
    )


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

@router.get("/styles", tags=["system"])
def list_styles():
    """Return the names of all available CSS resume styles."""
    from app.services.document_service import list_available_styles
    return {"styles": list_available_styles()}
