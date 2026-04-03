"""
Async background task definitions for document generation.

Tasks are executed by the APScheduler ``BackgroundScheduler`` (thread-pool
executor) so they run in worker threads without blocking the FastAPI event
loop.  Each task:

1. Updates the :class:`~src.database.TaskRecord` status to ``running``.
2. Reports incremental progress via :func:`~src.database.update_task_progress`.
3. On success, saves document metadata via :func:`~src.database.save_document`
   and marks the task ``completed``.
4. On failure, calls :func:`~src.database.fail_task` and optionally retries
   up to ``cfg.task_max_retries`` times with a ``cfg.task_retry_delay`` second
   back-off.

Usage
-----
    from src.web.tasks import task_manager

    task_id = task_manager.submit_resume(style_name="cloyola")
    task_id = task_manager.submit_tailored_resume(job_url="https://...", style_name="cloyola")
    task_id = task_manager.submit_cover_letter(job_url="https://...", style_name="cloyola")
"""

from __future__ import annotations

import base64
import time
import uuid
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

from src.config import get_config
from src.database import (
    create_task,
    fail_task,
    get_task,
    save_document,
    update_task_progress,
)
from src.errors import (
    BrowserInitError,
    DocumentGenerationError,
    LLMError,
    StyleNotFoundError,
    TaskNotFoundError,
)
from src.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_resume_text(data_folder: Path) -> str:
    """Read the plain-text resume YAML from *data_folder*."""
    from src.utils.constants import PLAIN_TEXT_RESUME_YAML

    resume_path = data_folder / PLAIN_TEXT_RESUME_YAML
    if not resume_path.exists():
        raise FileNotFoundError(f"Plain text resume not found: {resume_path}")
    return resume_path.read_text(encoding="utf-8")


def _load_api_key(data_folder: Path) -> str:
    """Read the LLM API key from *data_folder/secrets.yaml*."""
    import yaml
    from src.utils.constants import SECRETS_YAML

    secrets_path = data_folder / SECRETS_YAML
    if not secrets_path.exists():
        raise FileNotFoundError(f"Secrets file not found: {secrets_path}")
    secrets = yaml.safe_load(secrets_path.read_text(encoding="utf-8"))
    api_key = secrets.get("llm_api_key", "")
    if not api_key:
        raise ValueError("llm_api_key is empty in secrets.yaml")
    return api_key


def _resolve_style(style_manager, style_name: Optional[str]) -> str:
    """Return *style_name* if valid, otherwise the first available style."""
    available = style_manager.get_styles()
    if not available:
        raise StyleNotFoundError(style_name or "<none>")
    if style_name and style_name in available:
        return style_name
    # Fall back to first available style
    first = next(iter(available))
    log.debug("Style '{}' not found; falling back to '{}'", style_name, first)
    return first


def _save_pdf_to_disk(pdf_data: bytes, output_dir: Path, file_name: str) -> Path:
    """Write *pdf_data* to *output_dir / file_name* and return the path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / file_name
    output_path.write_bytes(pdf_data)
    return output_path


# ---------------------------------------------------------------------------
# Task worker functions (run in thread-pool)
# ---------------------------------------------------------------------------

def _run_generate_resume(task_id: str, style_name: Optional[str]) -> None:
    """Worker: generate a plain resume PDF."""
    cfg = get_config()
    log.info("Task {}: starting plain resume generation", task_id)

    try:
        update_task_progress(task_id, 5, "Loading resume data", status="running")

        plain_text_resume = _load_resume_text(cfg.data_folder)
        api_key = _load_api_key(cfg.data_folder)

        update_task_progress(task_id, 15, "Initialising style manager")

        from src.libs.resume_and_cover_builder import (
            ResumeFacade,
            ResumeGenerator,
            StyleManager,
        )
        from src.resume_schemas.resume import Resume

        style_manager = StyleManager()
        resolved_style = _resolve_style(style_manager, style_name)
        style_manager.set_selected_style(resolved_style)

        update_task_progress(task_id, 25, "Initialising browser")

        from src.utils.chrome_utils import init_browser

        driver = init_browser()

        update_task_progress(task_id, 40, "Building resume object")

        resume_object = Resume(plain_text_resume)
        resume_generator = ResumeGenerator()
        resume_generator.set_resume_object(resume_object)

        output_path = cfg.output_folder
        resume_facade = ResumeFacade(
            api_key=api_key,
            style_manager=style_manager,
            resume_generator=resume_generator,
            resume_object=resume_object,
            output_path=output_path,
        )
        resume_facade.set_driver(driver)

        update_task_progress(task_id, 60, "Generating resume HTML and converting to PDF")

        result_base64 = resume_facade.create_resume_pdf()
        pdf_data = base64.b64decode(result_base64)

        update_task_progress(task_id, 85, "Saving PDF to disk")

        file_name = "resume_base.pdf"
        saved_path = _save_pdf_to_disk(pdf_data, Path(cfg.output_folder), file_name)

        save_document(
            task_id=task_id,
            document_type="resume",
            file_name=file_name,
            file_path=str(saved_path),
            file_size=len(pdf_data),
            style_name=resolved_style,
        )

        update_task_progress(task_id, 100, "Resume generated successfully", status="completed")
        log.info("Task {}: resume saved to {}", task_id, saved_path)

    except Exception as exc:
        log.exception("Task {}: resume generation failed: {}", task_id, exc)
        fail_task(task_id, str(exc))
        raise


def _run_generate_tailored_resume(
    task_id: str, job_url: str, style_name: Optional[str]
) -> None:
    """Worker: generate a job-tailored resume PDF."""
    cfg = get_config()
    log.info("Task {}: starting tailored resume generation for {}", task_id, job_url)

    try:
        update_task_progress(task_id, 5, "Loading resume data", status="running")

        plain_text_resume = _load_resume_text(cfg.data_folder)
        api_key = _load_api_key(cfg.data_folder)

        update_task_progress(task_id, 15, "Initialising style manager")

        from src.libs.resume_and_cover_builder import (
            ResumeFacade,
            ResumeGenerator,
            StyleManager,
        )
        from src.resume_schemas.resume import Resume

        style_manager = StyleManager()
        resolved_style = _resolve_style(style_manager, style_name)
        style_manager.set_selected_style(resolved_style)

        update_task_progress(task_id, 25, "Initialising browser")

        from src.utils.chrome_utils import init_browser

        driver = init_browser()

        update_task_progress(task_id, 35, "Parsing job description from URL")

        resume_object = Resume(plain_text_resume)
        resume_generator = ResumeGenerator()
        resume_generator.set_resume_object(resume_object)

        output_path = cfg.output_folder
        resume_facade = ResumeFacade(
            api_key=api_key,
            style_manager=style_manager,
            resume_generator=resume_generator,
            resume_object=resume_object,
            output_path=output_path,
        )
        resume_facade.set_driver(driver)
        resume_facade.link_to_job(job_url)

        update_task_progress(task_id, 60, "Generating tailored resume HTML and converting to PDF")

        result_base64, suggested_name = resume_facade.create_resume_pdf_job_tailored()
        pdf_data = base64.b64decode(result_base64)

        update_task_progress(task_id, 85, "Saving PDF to disk")

        output_dir = Path(cfg.output_folder) / suggested_name
        file_name = "resume_tailored.pdf"
        saved_path = _save_pdf_to_disk(pdf_data, output_dir, file_name)

        save_document(
            task_id=task_id,
            document_type="resume",
            file_name=file_name,
            file_path=str(saved_path),
            file_size=len(pdf_data),
            style_name=resolved_style,
            job_url=job_url,
        )

        update_task_progress(
            task_id, 100, "Tailored resume generated successfully", status="completed"
        )
        log.info("Task {}: tailored resume saved to {}", task_id, saved_path)

    except Exception as exc:
        log.exception("Task {}: tailored resume generation failed: {}", task_id, exc)
        fail_task(task_id, str(exc))
        raise


def _run_generate_cover_letter(
    task_id: str, job_url: str, style_name: Optional[str]
) -> None:
    """Worker: generate a cover letter PDF."""
    cfg = get_config()
    log.info("Task {}: starting cover letter generation for {}", task_id, job_url)

    try:
        update_task_progress(task_id, 5, "Loading resume data", status="running")

        plain_text_resume = _load_resume_text(cfg.data_folder)
        api_key = _load_api_key(cfg.data_folder)

        update_task_progress(task_id, 15, "Initialising style manager")

        from src.libs.resume_and_cover_builder import (
            ResumeFacade,
            ResumeGenerator,
            StyleManager,
        )
        from src.resume_schemas.resume import Resume

        style_manager = StyleManager()
        resolved_style = _resolve_style(style_manager, style_name)
        style_manager.set_selected_style(resolved_style)

        update_task_progress(task_id, 25, "Initialising browser")

        from src.utils.chrome_utils import init_browser

        driver = init_browser()

        update_task_progress(task_id, 35, "Parsing job description from URL")

        resume_object = Resume(plain_text_resume)
        resume_generator = ResumeGenerator()
        resume_generator.set_resume_object(resume_object)

        output_path = cfg.output_folder
        resume_facade = ResumeFacade(
            api_key=api_key,
            style_manager=style_manager,
            resume_generator=resume_generator,
            resume_object=resume_object,
            output_path=output_path,
        )
        resume_facade.set_driver(driver)
        resume_facade.link_to_job(job_url)

        update_task_progress(task_id, 60, "Generating cover letter HTML and converting to PDF")

        result_base64, suggested_name = resume_facade.create_cover_letter()
        pdf_data = base64.b64decode(result_base64)

        update_task_progress(task_id, 85, "Saving PDF to disk")

        output_dir = Path(cfg.output_folder) / suggested_name
        file_name = "cover_letter_tailored.pdf"
        saved_path = _save_pdf_to_disk(pdf_data, output_dir, file_name)

        save_document(
            task_id=task_id,
            document_type="cover_letter",
            file_name=file_name,
            file_path=str(saved_path),
            file_size=len(pdf_data),
            style_name=resolved_style,
            job_url=job_url,
        )

        update_task_progress(
            task_id, 100, "Cover letter generated successfully", status="completed"
        )
        log.info("Task {}: cover letter saved to {}", task_id, saved_path)

    except Exception as exc:
        log.exception("Task {}: cover letter generation failed: {}", task_id, exc)
        fail_task(task_id, str(exc))
        raise


# ---------------------------------------------------------------------------
# TaskManager – scheduler wrapper
# ---------------------------------------------------------------------------

class TaskManager:
    """Manages the APScheduler instance and provides task submission methods.

    The scheduler uses a ``ThreadPoolExecutor`` so that blocking Selenium /
    LLM calls do not stall the FastAPI event loop.
    """

    def __init__(self) -> None:
        cfg = get_config()
        executors = {
            "default": ThreadPoolExecutor(max_workers=cfg.task_max_workers),
        }
        self._scheduler = BackgroundScheduler(executors=executors)
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background scheduler."""
        if not self._started:
            self._scheduler.start()
            self._started = True
            log.info("TaskManager scheduler started")

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the scheduler gracefully."""
        if self._started:
            self._scheduler.shutdown(wait=wait)
            self._started = False
            log.info("TaskManager scheduler stopped")

    # ------------------------------------------------------------------
    # Task submission
    # ------------------------------------------------------------------

    def _submit(self, func, task_id: str, *args) -> str:
        """Schedule *func* to run immediately in the thread pool."""
        self._scheduler.add_job(
            func,
            args=(task_id, *args),
            id=task_id,
            replace_existing=True,
            misfire_grace_time=None,
        )
        log.debug("Submitted job {} to scheduler", task_id)
        return task_id

    def submit_resume(self, style_name: Optional[str] = None) -> str:
        """Queue a plain resume generation task and return its task ID."""
        record = create_task(task_type="resume", style_name=style_name)
        task_id = record.id
        return self._submit(_run_generate_resume, task_id, style_name)

    def submit_tailored_resume(
        self, job_url: str, style_name: Optional[str] = None
    ) -> str:
        """Queue a tailored resume generation task and return its task ID."""
        record = create_task(
            task_type="resume_tailored", job_url=job_url, style_name=style_name
        )
        task_id = record.id
        return self._submit(_run_generate_tailored_resume, task_id, job_url, style_name)

    def submit_cover_letter(
        self, job_url: str, style_name: Optional[str] = None
    ) -> str:
        """Queue a cover letter generation task and return its task ID."""
        record = create_task(
            task_type="cover_letter", job_url=job_url, style_name=style_name
        )
        task_id = record.id
        return self._submit(_run_generate_cover_letter, task_id, job_url, style_name)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

task_manager = TaskManager()
