"""
Custom exception classes and FastAPI error handlers.

Usage
-----
Register the handlers in ``app/main.py``::

    from app.api.errors import register_error_handlers
    register_error_handlers(app)
"""
from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.utils.logger import logger


# ---------------------------------------------------------------------------
# Custom exception hierarchy
# ---------------------------------------------------------------------------

class AIHawkError(Exception):
    """Base class for all application-specific errors."""
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, detail: str | None = None):
        self.message = message or self.default_message
        self.detail = detail  # internal detail – logged but NOT sent to client
        super().__init__(self.message)


class NotConfiguredError(AIHawkError):
    """Raised when a required configuration (API key, resume …) is missing."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "Application is not fully configured."


class ValidationError_(AIHawkError):
    """Raised when user-supplied data fails validation."""
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_message = "Validation failed."


class ResourceNotFoundError(AIHawkError):
    """Raised when a requested resource does not exist."""
    status_code = status.HTTP_404_NOT_FOUND
    default_message = "Resource not found."


class DocumentGenerationError(AIHawkError):
    """Raised when document generation fails."""
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_message = "Document generation failed."


class TaskNotFoundError(ResourceNotFoundError):
    """Raised when a task ID cannot be found."""
    default_message = "Task not found."


class ExternalAPIError(AIHawkError):
    """Raised when an upstream API (LLM provider) returns an error."""
    status_code = status.HTTP_502_BAD_GATEWAY
    default_message = "External API error."


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _error_response(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "message": message},
    )


# ---------------------------------------------------------------------------
# FastAPI exception handlers
# ---------------------------------------------------------------------------

def register_error_handlers(app: FastAPI) -> None:
    """Attach all custom exception handlers to *app*."""

    @app.exception_handler(AIHawkError)
    async def _aihawk_error_handler(request: Request, exc: AIHawkError) -> JSONResponse:
        if exc.detail:
            logger.error(
                "AIHawkError [{}] on {} {}: {} | detail: {}",
                exc.__class__.__name__,
                request.method,
                request.url.path,
                exc.message,
                exc.detail,
            )
        else:
            logger.warning(
                "AIHawkError [{}] on {} {}: {}",
                exc.__class__.__name__,
                request.method,
                request.url.path,
                exc.message,
            )
        return _error_response(exc.status_code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        logger.warning(
            "Request validation error on {} {}: {}",
            request.method,
            request.url.path,
            errors,
        )
        # Flatten the pydantic error list into a human-readable string.
        messages = "; ".join(
            f"{' -> '.join(str(loc) for loc in e['loc'])}: {e['msg']}"
            for e in errors
        )
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Validation error: {messages}",
        )

    @app.exception_handler(Exception)
    async def _generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled exception on {} {}: {}",
            request.method,
            request.url.path,
            exc,
        )
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "An internal server error occurred. Please try again later.",
        )
