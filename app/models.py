"""
Pydantic request / response models used by the API layer.

These are *not* the SQLAlchemy ORM models (those live in ``app/schemas.py``).
"""
from __future__ import annotations

import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Setup / API key
# ---------------------------------------------------------------------------

class SetupRequest(BaseModel):
    api_key: str = Field(..., min_length=10, description="LLM provider API key")
    resume_content: Optional[str] = Field(None, description="Plain-text YAML resume (optional at setup)")


class SetupResponse(BaseModel):
    success: bool
    message: str
    user_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

class ResumeUploadResponse(BaseModel):
    success: bool
    message: str
    resume_id: Optional[int] = None
    size: Optional[int] = None


class ResumeInfo(BaseModel):
    id: int
    size: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

class PreferencesRequest(BaseModel):
    positions: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote: bool = True
    experience_level: dict[str, bool] = Field(default_factory=dict)
    job_types: dict[str, bool] = Field(default_factory=dict)
    date: dict[str, bool] = Field(default_factory=dict)
    distance: int = Field(default=50, ge=0, le=200)
    company_blacklist: list[str] = Field(default_factory=list)
    title_blacklist: list[str] = Field(default_factory=list)
    location_blacklist: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class PreferencesResponse(BaseModel):
    success: bool
    message: str
    preference_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Document generation
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    doc_type: str = Field(
        ...,
        description="One of: 'resume', 'tailored_resume', 'cover_letter'",
    )
    job_url: Optional[str] = Field(
        None,
        description="Job posting URL (required for tailored_resume and cover_letter)",
    )
    style: Optional[str] = Field(None, description="CSS style name to use")

    @field_validator("doc_type")
    @classmethod
    def _valid_doc_type(cls, v: str) -> str:
        allowed = {"resume", "tailored_resume", "cover_letter"}
        if v not in allowed:
            raise ValueError(f"doc_type must be one of {allowed}")
        return v


class GenerateResponse(BaseModel):
    success: bool
    task_id: str
    message: str


# ---------------------------------------------------------------------------
# Task status
# ---------------------------------------------------------------------------

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: int
    task_type: str
    error: Optional[str] = None
    document_id: Optional[int] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class DocumentInfo(BaseModel):
    id: int
    doc_type: str
    filename: str
    created_at: datetime.datetime
    task_id: Optional[str] = None

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo]
    total: int


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

class StatusResponse(BaseModel):
    has_api_key: bool
    has_resume: bool
    has_preferences: bool
    app_version: str
    ready: bool


# ---------------------------------------------------------------------------
# Generic
# ---------------------------------------------------------------------------

class MessageResponse(BaseModel):
    success: bool
    message: str
