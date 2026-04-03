"""
FastAPI application factory for the AIHawk web server.

The application exposes a REST API for:
- Async document generation (resume, tailored resume, cover letter)
- Task status polling with progress tracking
- Document download
- User preference management
- Available style listing
- Health check

Startup / shutdown lifecycle hooks initialise the database schema and
start / stop the APScheduler background task manager.

Usage
-----
    # Run directly (development)
    python -m src.web.app

    # Via main.py --web flag
    python main.py --web

    # Via uvicorn (production)
    uvicorn src.web.app:create_app --factory --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, Path, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config import get_config
from src.database import init_db
from src.logger import AppLogger, get_logger
from src.web.handlers import (
    handle_download_document,
    handle_generate_cover_letter,
    handle_generate_resume,
    handle_generate_tailored_resume,
    handle_get_preference,
    handle_get_task_status,
    handle_health,
    handle_list_styles,
    handle_list_task_documents,
    handle_set_preference,
)
from src.web.models import (
    DocumentResponse,
    ErrorResponse,
    GenerateCoverLetterRequest,
    GenerateResumeRequest,
    GenerateTailoredResumeRequest,
    HealthResponse,
    PreferenceRequest,
    PreferenceResponse,
    StyleListResponse,
    TaskResponse,
    TaskStatusResponse,
)
from src.web.tasks import task_manager

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Initialise resources on startup and clean up on shutdown."""
    cfg = get_config()

    # Configure logging
    AppLogger.configure(
        log_level=cfg.log_level,
        to_file=cfg.log_to_file,
        to_console=cfg.log_to_console,
        log_dir=cfg.log_dir,
    )

    log.info("AIHawk web server starting up")

    # Initialise database
    init_db()

    # Start background task scheduler
    task_manager.start()
    log.info("Background task manager started")

    yield  # Application runs here

    # Graceful shutdown
    log.info("AIHawk web server shutting down")
    task_manager.shutdown(wait=True)
    log.info("Background task manager stopped")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    cfg = get_config()

    app = FastAPI(
        title="AIHawk Document Generator API",
        description=(
            "REST API for asynchronous resume and cover letter generation. "
            "Submit a generation task, poll for progress, and download the resulting PDF."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=_lifespan,
    )

    # ------------------------------------------------------------------
    # CORS middleware
    # ------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Global exception handler
    # ------------------------------------------------------------------

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        log.exception("Unhandled exception on {}: {}", request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="internal_server_error",
                message="An unexpected error occurred. Please try again later.",
                details=str(exc),
            ).model_dump(),
        )

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    # Health
    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["Health"],
        summary="API health check",
    )
    async def health():
        return handle_health()

    # Styles
    @app.get(
        "/styles",
        response_model=StyleListResponse,
        tags=["Styles"],
        summary="List available document styles",
    )
    async def list_styles():
        return handle_list_styles()

    # Document generation
    @app.post(
        "/generate/resume",
        response_model=TaskResponse,
        status_code=202,
        tags=["Generation"],
        summary="Generate a plain resume PDF",
        description=(
            "Queues a background task to generate a resume PDF from the configured "
            "plain_text_resume.yaml. Returns a task ID for progress polling."
        ),
    )
    async def generate_resume(request: GenerateResumeRequest):
        return handle_generate_resume(request)

    @app.post(
        "/generate/resume/tailored",
        response_model=TaskResponse,
        status_code=202,
        tags=["Generation"],
        summary="Generate a job-tailored resume PDF",
        description=(
            "Queues a background task to generate a resume tailored to the provided "
            "job URL. The job description is fetched and used to customise the resume."
        ),
    )
    async def generate_tailored_resume(request: GenerateTailoredResumeRequest):
        return handle_generate_tailored_resume(request)

    @app.post(
        "/generate/cover-letter",
        response_model=TaskResponse,
        status_code=202,
        tags=["Generation"],
        summary="Generate a tailored cover letter PDF",
        description=(
            "Queues a background task to generate a cover letter tailored to the "
            "provided job URL."
        ),
    )
    async def generate_cover_letter(request: GenerateCoverLetterRequest):
        return handle_generate_cover_letter(request)

    # Task status
    @app.get(
        "/tasks/{task_id}",
        response_model=TaskStatusResponse,
        tags=["Tasks"],
        summary="Get task status and progress",
        description=(
            "Poll this endpoint to track the progress of a generation task. "
            "When status is 'completed', the 'documents' field contains download links."
        ),
    )
    async def get_task_status(
        task_id: str = Path(..., description="Task ID returned by a generation endpoint"),
    ):
        return handle_get_task_status(task_id)

    @app.get(
        "/tasks/{task_id}/documents",
        response_model=List[DocumentResponse],
        tags=["Tasks"],
        summary="List documents produced by a task",
    )
    async def list_task_documents(
        task_id: str = Path(..., description="Task ID"),
    ):
        return handle_list_task_documents(task_id)

    @app.get(
        "/tasks/{task_id}/documents/{document_id}/download",
        tags=["Tasks"],
        summary="Download a generated PDF document",
        response_description="PDF file stream",
    )
    async def download_document(
        task_id: str = Path(..., description="Task ID"),
        document_id: str = Path(..., description="Document ID"),
    ):
        return handle_download_document(task_id, document_id)

    # Preferences
    @app.post(
        "/preferences",
        response_model=PreferenceResponse,
        tags=["Preferences"],
        summary="Set a user preference",
    )
    async def set_preference(request: PreferenceRequest):
        return handle_set_preference(request)

    @app.get(
        "/preferences/{key}",
        response_model=PreferenceResponse,
        tags=["Preferences"],
        summary="Get a user preference",
    )
    async def get_preference(
        key: str = Path(..., description="Preference key"),
    ):
        return handle_get_preference(key)

    return app


# ---------------------------------------------------------------------------
# Module-level app instance (for uvicorn / gunicorn direct import)
# ---------------------------------------------------------------------------

app = create_app()


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    cfg = get_config()
    uvicorn.run(
        "src.web.app:app",
        host=cfg.web_host,
        port=cfg.web_port,
        reload=cfg.web_reload,
        log_level=cfg.log_level.lower(),
    )
