"""
FastAPI application factory and entry point.

This module:
- Creates the FastAPI app instance
- Registers middleware (CORS, request logging)
- Mounts the API router under ``/api``
- Serves the web UI (``app/web/static/index.html``) from the root path
- Initialises the database on startup
- Exposes ``app`` for use by uvicorn / gunicorn

Running directly
----------------
    python -m app.main          # starts uvicorn with settings from config.py
    uvicorn app.main:app        # production-style
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.errors import register_error_handlers
from app.api.routes import router as api_router
from app.config import settings
from app.database import init_db
from app.utils.logger import configure_logging, logger

# ---------------------------------------------------------------------------
# Logging – configure as early as possible
# ---------------------------------------------------------------------------
configure_logging(
    log_level=settings.log_level,
    log_to_file=settings.log_to_file,
    log_to_console=settings.log_to_console,
    log_dir=settings.log_dir,
)

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "AIHawk Jobs Applier – async document generation service. "
            "Use the web UI at / or the REST API under /api."
        ),
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Request timing middleware
    # ------------------------------------------------------------------
    @app.middleware("http")
    async def _add_process_time_header(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        response.headers["X-Process-Time"] = f"{elapsed:.4f}s"
        logger.debug(
            "{} {} → {} ({:.4f}s)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed,
        )
        return response

    # ------------------------------------------------------------------
    # Error handlers
    # ------------------------------------------------------------------
    register_error_handlers(app)

    # ------------------------------------------------------------------
    # API routes
    # ------------------------------------------------------------------
    app.include_router(api_router, prefix="/api")

    # ------------------------------------------------------------------
    # Static files / web UI
    # ------------------------------------------------------------------
    static_dir = Path(__file__).parent / "web" / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/", include_in_schema=False)
        async def _serve_ui():
            index = static_dir / "index.html"
            if index.exists():
                return FileResponse(str(index))
            return JSONResponse({"message": "Web UI not found."}, status_code=404)

    # ------------------------------------------------------------------
    # Startup / shutdown events
    # ------------------------------------------------------------------
    @app.on_event("startup")
    async def _startup():
        logger.info("Starting {} v{}", settings.app_name, settings.app_version)
        init_db()
        logger.info("Application ready – listening on {}:{}", settings.host, settings.port)

    @app.on_event("shutdown")
    async def _shutdown():
        logger.info("Shutting down {}", settings.app_name)

    return app


# ---------------------------------------------------------------------------
# Module-level app instance (used by uvicorn)
# ---------------------------------------------------------------------------
app = create_app()


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level=settings.log_level.lower(),
    )
