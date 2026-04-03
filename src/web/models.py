"""
Pydantic request / response models for the AIHawk web API.

All models use strict validation and provide clear field descriptions so
that the auto-generated OpenAPI docs are self-documenting.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class TaskType(str, Enum):
    """Supported document-generation task types."""
    resume = "resume"
    resume_tailored = "resume_tailored"
    cover_letter = "cover_letter"


class TaskStatus(str, Enum):
    """Lifecycle states for a background task."""
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    retrying = "retrying"


class DocumentType(str, Enum):
    """Types of generated documents."""
    resume = "resume"
    cover_letter = "cover_letter"


# ---------------------------------------------------------------------------
# Task models
# ---------------------------------------------------------------------------

class GenerateResumeRequest(BaseModel):
    """Request body for generating a plain (non-tailored) resume PDF."""

    style_name: Optional[str] = Field(
        None,
        description="Name of the CSS style to apply. If omitted the first available style is used.",
        examples=["cloyola"],
    )


class GenerateTailoredResumeRequest(BaseModel):
    """Request body for generating a resume tailored to a specific job."""

    job_url: str = Field(
        ...,
        description="Public URL of the job posting to tailor the resume against.",
        examples=["https://www.linkedin.com/jobs/view/123456789/"],
    )
    style_name: Optional[str] = Field(
        None,
        description="Name of the CSS style to apply.",
    )

    @field_validator("job_url")
    @classmethod
    def job_url_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("job_url must not be empty")
        return v.strip()


class GenerateCoverLetterRequest(BaseModel):
    """Request body for generating a cover letter tailored to a specific job."""

    job_url: str = Field(
        ...,
        description="Public URL of the job posting.",
        examples=["https://www.linkedin.com/jobs/view/123456789/"],
    )
    style_name: Optional[str] = Field(
        None,
        description="Name of the CSS style to apply.",
    )

    @field_validator("job_url")
    @classmethod
    def job_url_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("job_url must not be empty")
        return v.strip()


# ---------------------------------------------------------------------------
# Task response models
# ---------------------------------------------------------------------------

class TaskResponse(BaseModel):
    """Returned immediately when a task is accepted."""

    task_id: str = Field(..., description="Unique identifier for the queued task.")
    task_type: TaskType
    status: TaskStatus
    message: str = Field("", description="Human-readable status description.")

    model_config = {"from_attributes": True}


class TaskStatusResponse(BaseModel):
    """Detailed status of a background task, suitable for polling."""

    task_id: str
    task_type: str
    status: TaskStatus
    progress: int = Field(0, ge=0, le=100, description="Completion percentage (0-100).")
    message: str = ""
    error: Optional[str] = None
    retries: int = 0
    job_url: Optional[str] = None
    style_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    documents: List["DocumentResponse"] = Field(
        default_factory=list,
        description="Documents produced by this task (populated when completed).",
    )

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Document models
# ---------------------------------------------------------------------------

class DocumentResponse(BaseModel):
    """Metadata for a generated document."""

    id: str
    task_id: str
    document_type: DocumentType
    file_name: str
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    style_name: Optional[str] = None
    job_url: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# Resolve forward reference
TaskStatusResponse.model_rebuild()


# ---------------------------------------------------------------------------
# Style models
# ---------------------------------------------------------------------------

class StyleInfo(BaseModel):
    """Information about an available document style."""

    name: str = Field(..., description="Style identifier used in generation requests.")
    author_link: str = Field(..., description="URL or name of the style author.")
    file_name: str = Field(..., description="CSS file name on disk.")


class StyleListResponse(BaseModel):
    """List of available document styles."""

    styles: List[StyleInfo]
    total: int


# ---------------------------------------------------------------------------
# Health / info models
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """API health check response."""

    status: str = "ok"
    version: str = "1.0.0"
    database: str = "ok"


class ErrorResponse(BaseModel):
    """Standard error envelope returned on 4xx / 5xx responses."""

    error: str = Field(..., description="Short error code or type.")
    message: str = Field(..., description="Human-readable error description.")
    details: Optional[Any] = Field(None, description="Additional structured context.")


# ---------------------------------------------------------------------------
# Preference models
# ---------------------------------------------------------------------------

class PreferenceRequest(BaseModel):
    """Set a single user preference."""

    key: str = Field(..., min_length=1, max_length=128)
    value: str = Field(..., max_length=4096)


class PreferenceResponse(BaseModel):
    """A single user preference key-value pair."""

    key: str
    value: Optional[str]
    updated_at: Optional[datetime] = None
