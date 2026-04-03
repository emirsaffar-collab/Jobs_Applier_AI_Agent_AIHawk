"""
Document generation service.

Wraps the existing ``lib_resume_builder_AIHawk`` library (``ResumeFacade``,
``ResumeGenerator``, ``StyleManager``) and exposes three high-level functions:

- ``generate_resume``          – base resume PDF (no job description)
- ``generate_tailored_resume`` – resume tailored to a specific job URL
- ``generate_cover_letter``    – cover letter tailored to a specific job URL

All three functions return raw PDF bytes.

The service is intentionally synchronous so it can be called from both
Celery tasks and the CLI without any async overhead.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from app.utils.logger import logger
from app.config import settings

# ---------------------------------------------------------------------------
# Lazy imports of the heavy resume-builder library so the module can be
# imported without Selenium / Chrome being available (e.g. during tests).
# ---------------------------------------------------------------------------

def _build_resume_facade(api_key: str, style_name: Optional[str] = None):
    """
    Construct and return a configured ``ResumeFacade`` instance.

    Raises
    ------
    RuntimeError
        If Chrome / ChromeDriver cannot be initialised.
    ValueError
        If *style_name* is provided but does not exist.
    """
    from src.libs.resume_and_cover_builder import ResumeFacade, ResumeGenerator, StyleManager

    style_manager = StyleManager()
    available_styles = style_manager.get_styles()

    if style_name:
        if style_name not in available_styles:
            raise ValueError(
                f"Style '{style_name}' not found. "
                f"Available styles: {list(available_styles.keys())}"
            )
        style_manager.set_selected_style(style_name)
    elif available_styles:
        # Default to the first available style.
        default_style = next(iter(available_styles))
        style_manager.set_selected_style(default_style)
        logger.info("No style specified; defaulting to '{}'", default_style)
    else:
        logger.warning("No CSS styles found in the styles directory.")

    resume_generator = ResumeGenerator()
    output_path = settings.output_path

    facade = ResumeFacade(
        api_key=api_key,
        style_manager=style_manager,
        resume_generator=resume_generator,
        resume_object=None,  # set later via set_resume_object
        output_path=output_path,
    )
    return facade, resume_generator, style_manager


def _init_browser():
    """Initialise and return a headless Chrome WebDriver."""
    from src.utils.chrome_utils import init_browser
    return init_browser()


def _decode_pdf(b64_data: str) -> bytes:
    try:
        return base64.b64decode(b64_data)
    except Exception as exc:
        raise ValueError(f"Failed to decode PDF base64 data: {exc}") from exc


# ---------------------------------------------------------------------------
# Public generation functions
# ---------------------------------------------------------------------------

def generate_resume(
    api_key: str,
    resume_yaml: str,
    style_name: Optional[str] = None,
) -> bytes:
    """
    Generate a base (non-tailored) resume PDF.

    Parameters
    ----------
    api_key:
        LLM provider API key.
    resume_yaml:
        Plain-text YAML resume content.
    style_name:
        Optional CSS style name.  Defaults to the first available style.

    Returns
    -------
    bytes
        Raw PDF content.
    """
    from src.resume_schemas.resume import Resume

    logger.info("Starting base resume generation")
    resume_object = Resume(resume_yaml)

    facade, resume_generator, _ = _build_resume_facade(api_key, style_name)
    resume_generator.set_resume_object(resume_object)
    facade.resume_generator = resume_generator

    driver = _init_browser()
    try:
        facade.set_driver(driver)
        result_b64 = facade.create_resume_pdf()
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    pdf_bytes = _decode_pdf(result_b64)
    logger.info("Base resume generation completed ({} bytes)", len(pdf_bytes))
    return pdf_bytes


def generate_tailored_resume(
    api_key: str,
    resume_yaml: str,
    job_url: str,
    style_name: Optional[str] = None,
) -> tuple[bytes, str]:
    """
    Generate a job-tailored resume PDF.

    Returns
    -------
    tuple[bytes, str]
        ``(pdf_bytes, suggested_filename_stem)``
    """
    from src.resume_schemas.resume import Resume

    logger.info("Starting tailored resume generation for job URL: {}", job_url)
    resume_object = Resume(resume_yaml)

    facade, resume_generator, _ = _build_resume_facade(api_key, style_name)
    resume_generator.set_resume_object(resume_object)
    facade.resume_generator = resume_generator

    driver = _init_browser()
    try:
        facade.set_driver(driver)
        facade.link_to_job(job_url)
        result_b64, suggested_name = facade.create_resume_pdf_job_tailored()
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    pdf_bytes = _decode_pdf(result_b64)
    logger.info(
        "Tailored resume generation completed ({} bytes, name={})",
        len(pdf_bytes),
        suggested_name,
    )
    return pdf_bytes, suggested_name


def generate_cover_letter(
    api_key: str,
    resume_yaml: str,
    job_url: str,
    style_name: Optional[str] = None,
) -> tuple[bytes, str]:
    """
    Generate a cover letter PDF tailored to a specific job.

    Returns
    -------
    tuple[bytes, str]
        ``(pdf_bytes, suggested_filename_stem)``
    """
    from src.resume_schemas.resume import Resume

    logger.info("Starting cover letter generation for job URL: {}", job_url)
    resume_object = Resume(resume_yaml)

    facade, resume_generator, _ = _build_resume_facade(api_key, style_name)
    resume_generator.set_resume_object(resume_object)
    facade.resume_generator = resume_generator

    driver = _init_browser()
    try:
        facade.set_driver(driver)
        facade.link_to_job(job_url)
        result_b64, suggested_name = facade.create_cover_letter()
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    pdf_bytes = _decode_pdf(result_b64)
    logger.info(
        "Cover letter generation completed ({} bytes, name={})",
        len(pdf_bytes),
        suggested_name,
    )
    return pdf_bytes, suggested_name


# ---------------------------------------------------------------------------
# Available styles helper
# ---------------------------------------------------------------------------

def list_available_styles() -> list[str]:
    """Return the names of all available CSS resume styles."""
    try:
        from src.libs.resume_and_cover_builder import StyleManager
        sm = StyleManager()
        return list(sm.get_styles().keys())
    except Exception as exc:
        logger.warning("Could not enumerate styles: {}", exc)
        return []
