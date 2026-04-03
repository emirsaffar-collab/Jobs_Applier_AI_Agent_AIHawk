"""
CLI interface for AIHawk Jobs Applier.

Provides the same document-generation functionality as the web UI but driven
from the terminal.  All heavy lifting is delegated to the shared service layer
in ``app/services/`` so there is zero code duplication.

Usage
-----
    python -m cli.main                          # interactive menu
    python -m cli.main generate-resume          # generate base resume
    python -m cli.main generate-tailored        # tailored resume (prompts for URL)
    python -m cli.main generate-cover-letter    # cover letter (prompts for URL)
    python -m cli.main serve                    # start the web server
"""
from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml

# Ensure the project root is on sys.path when running as a script.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import settings
from app.database import db_session, init_db
from app.services.document_service import (
    generate_cover_letter,
    generate_resume,
    generate_tailored_resume,
    list_available_styles,
)
from app.services.preferences_service import save_preferences
from app.services.resume_service import get_resume_content, get_user_by_api_key, save_resume
from app.utils.logger import configure_logging, logger
from app.utils.validators import validate_api_key


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
configure_logging(
    log_level=settings.log_level,
    log_to_file=settings.log_to_file,
    log_to_console=True,
    log_dir=settings.log_dir,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_api_key(secrets_path: Path) -> str:
    """Load the LLM API key from a secrets YAML file."""
    if not secrets_path.exists():
        click.echo(f"[error] Secrets file not found: {secrets_path}", err=True)
        sys.exit(1)
    with open(secrets_path) as f:
        data = yaml.safe_load(f)
    key = data.get("llm_api_key", "")
    if not key:
        click.echo("[error] 'llm_api_key' is missing or empty in secrets.yaml", err=True)
        sys.exit(1)
    return key


def _load_resume(resume_path: Path) -> str:
    """Load plain-text YAML resume from *resume_path*."""
    if not resume_path.exists():
        click.echo(f"[error] Resume file not found: {resume_path}", err=True)
        sys.exit(1)
    return resume_path.read_text(encoding="utf-8")


def _pick_style(style_name: str | None) -> str | None:
    """Interactively pick a style if *style_name* is not provided."""
    styles = list_available_styles()
    if not styles:
        click.echo("[warning] No CSS styles found; proceeding without a style.")
        return None
    if style_name and style_name in styles:
        return style_name
    click.echo("\nAvailable styles:")
    for i, s in enumerate(styles, 1):
        click.echo(f"  {i}. {s}")
    while True:
        raw = click.prompt("Select a style number", default="1")
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(styles):
                return styles[idx]
        except ValueError:
            pass
        click.echo("Invalid selection, please try again.")


def _save_pdf(pdf_bytes: bytes, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(pdf_bytes)
    click.echo(f"[ok] Saved to: {output_path}")


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context):
    """AIHawk Jobs Applier – document generation CLI."""
    if ctx.invoked_subcommand is None:
        _interactive_menu()


# ---------------------------------------------------------------------------
# generate-resume
# ---------------------------------------------------------------------------

@cli.command("generate-resume")
@click.option("--data-folder", default="data_folder", show_default=True, help="Path to data folder")
@click.option("--style", default=None, help="CSS style name (omit to choose interactively)")
@click.option("--output", default=None, help="Output PDF path (default: data_folder/output/resume_base.pdf)")
def cmd_generate_resume(data_folder: str, style: str | None, output: str | None):
    """Generate a base (non-tailored) resume PDF."""
    data_path = Path(data_folder)
    api_key = _load_api_key(data_path / "secrets.yaml")
    resume_yaml = _load_resume(data_path / "plain_text_resume.yaml")
    style_name = _pick_style(style)
    out = Path(output) if output else data_path / "output" / "resume_base.pdf"

    click.echo("Generating resume…")
    try:
        pdf_bytes = generate_resume(api_key, resume_yaml, style_name)
        _save_pdf(pdf_bytes, out)
    except Exception as exc:
        click.echo(f"[error] {exc}", err=True)
        logger.exception("generate-resume failed: {}", exc)
        sys.exit(1)


# ---------------------------------------------------------------------------
# generate-tailored
# ---------------------------------------------------------------------------

@cli.command("generate-tailored")
@click.option("--data-folder", default="data_folder", show_default=True)
@click.option("--style", default=None)
@click.option("--job-url", default=None, help="Job posting URL (prompted if omitted)")
@click.option("--output", default=None)
def cmd_generate_tailored(data_folder: str, style: str | None, job_url: str | None, output: str | None):
    """Generate a job-tailored resume PDF."""
    data_path = Path(data_folder)
    api_key = _load_api_key(data_path / "secrets.yaml")
    resume_yaml = _load_resume(data_path / "plain_text_resume.yaml")
    style_name = _pick_style(style)

    if not job_url:
        job_url = click.prompt("Enter the job posting URL")

    click.echo(f"Generating tailored resume for: {job_url}")
    try:
        pdf_bytes, suggested_name = generate_tailored_resume(api_key, resume_yaml, job_url, style_name)
        out = Path(output) if output else data_path / "output" / f"resume_tailored_{suggested_name}.pdf"
        _save_pdf(pdf_bytes, out)
    except Exception as exc:
        click.echo(f"[error] {exc}", err=True)
        logger.exception("generate-tailored failed: {}", exc)
        sys.exit(1)


# ---------------------------------------------------------------------------
# generate-cover-letter
# ---------------------------------------------------------------------------

@cli.command("generate-cover-letter")
@click.option("--data-folder", default="data_folder", show_default=True)
@click.option("--style", default=None)
@click.option("--job-url", default=None, help="Job posting URL (prompted if omitted)")
@click.option("--output", default=None)
def cmd_generate_cover_letter(data_folder: str, style: str | None, job_url: str | None, output: str | None):
    """Generate a tailored cover letter PDF."""
    data_path = Path(data_folder)
    api_key = _load_api_key(data_path / "secrets.yaml")
    resume_yaml = _load_resume(data_path / "plain_text_resume.yaml")
    style_name = _pick_style(style)

    if not job_url:
        job_url = click.prompt("Enter the job posting URL")

    click.echo(f"Generating cover letter for: {job_url}")
    try:
        pdf_bytes, suggested_name = generate_cover_letter(api_key, resume_yaml, job_url, style_name)
        out = Path(output) if output else data_path / "output" / f"cover_letter_{suggested_name}.pdf"
        _save_pdf(pdf_bytes, out)
    except Exception as exc:
        click.echo(f"[error] {exc}", err=True)
        logger.exception("generate-cover-letter failed: {}", exc)
        sys.exit(1)


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------

@cli.command("serve")
@click.option("--host", default=settings.host, show_default=True)
@click.option("--port", default=settings.port, show_default=True)
@click.option("--reload", is_flag=True, default=False)
def cmd_serve(host: str, port: int, reload: bool):
    """Start the FastAPI web server."""
    import uvicorn
    click.echo(f"Starting web server on http://{host}:{port}")
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)


# ---------------------------------------------------------------------------
# Interactive menu (invoked when no sub-command is given)
# ---------------------------------------------------------------------------

def _interactive_menu():
    """Replicate the original inquirer-based interactive experience."""
    import inquirer  # type: ignore

    data_folder = Path("data_folder")
    secrets_path = data_folder / "secrets.yaml"
    resume_path = data_folder / "plain_text_resume.yaml"

    if not secrets_path.exists() or not resume_path.exists():
        click.echo(
            "[error] data_folder/secrets.yaml or data_folder/plain_text_resume.yaml not found.\n"
            "Please create them following the README instructions.",
            err=True,
        )
        sys.exit(1)

    api_key = _load_api_key(secrets_path)
    resume_yaml = _load_resume(resume_path)

    questions = [
        inquirer.List(
            "action",
            message="Select the action you want to perform:",
            choices=[
                "Generate Resume",
                "Generate Resume Tailored for Job Description",
                "Generate Tailored Cover Letter for Job Description",
                "Start Web Server",
                "Exit",
            ],
        )
    ]
    answer = inquirer.prompt(questions)
    if not answer:
        sys.exit(0)

    action = answer.get("action", "")

    if action == "Exit":
        sys.exit(0)

    if action == "Start Web Server":
        import uvicorn
        click.echo(f"Starting web server on http://{settings.host}:{settings.port}")
        uvicorn.run("app.main:app", host=settings.host, port=settings.port)
        return

    style_name = _pick_style(None)

    if action == "Generate Resume":
        click.echo("Generating resume…")
        try:
            pdf_bytes = generate_resume(api_key, resume_yaml, style_name)
            out = data_folder / "output" / "resume_base.pdf"
            _save_pdf(pdf_bytes, out)
        except Exception as exc:
            click.echo(f"[error] {exc}", err=True)
            logger.exception("Interactive generate-resume failed: {}", exc)

    elif action in (
        "Generate Resume Tailored for Job Description",
        "Generate Tailored Cover Letter for Job Description",
    ):
        job_url = click.prompt("Enter the job posting URL")

        if action == "Generate Resume Tailored for Job Description":
            click.echo("Generating tailored resume…")
            try:
                pdf_bytes, suggested_name = generate_tailored_resume(api_key, resume_yaml, job_url, style_name)
                out = data_folder / "output" / f"resume_tailored_{suggested_name}.pdf"
                _save_pdf(pdf_bytes, out)
            except Exception as exc:
                click.echo(f"[error] {exc}", err=True)
                logger.exception("Interactive generate-tailored failed: {}", exc)
        else:
            click.echo("Generating cover letter…")
            try:
                pdf_bytes, suggested_name = generate_cover_letter(api_key, resume_yaml, job_url, style_name)
                out = data_folder / "output" / f"cover_letter_{suggested_name}.pdf"
                _save_pdf(pdf_bytes, out)
            except Exception as exc:
                click.echo(f"[error] {exc}", err=True)
                logger.exception("Interactive generate-cover-letter failed: {}", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
