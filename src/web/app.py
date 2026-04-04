"""
FastAPI web server for AIHawk Jobs Applier — unified multi-platform job application bot.
Provides a web UI with async document generation, WebSocket progress updates,
and an automated job application bot supporting LinkedIn, Indeed, Glassdoor, ZipRecruiter, Dice.
"""
import asyncio
import base64
import hashlib
import os
import uuid
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from src.logging import logger

# Optional API key authentication — set WEB_API_KEY env var to enable
_WEB_API_KEY = os.environ.get("WEB_API_KEY", "")


class _OptionalAuthMiddleware(BaseHTTPMiddleware):
    """When WEB_API_KEY is set, require it in the Authorization header for API routes.

    Public routes (/, /api/health, /ws/*) are exempt. WebSocket auth is handled
    separately since middleware cannot intercept WS upgrades reliably.
    """

    EXEMPT_PATHS = {"/", "/api/health", "/docs", "/openapi.json"}

    async def dispatch(self, request: Request, call_next):
        if not _WEB_API_KEY:
            return await call_next(request)
        path = request.url.path
        if path in self.EXEMPT_PATHS or path.startswith("/ws/"):
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {_WEB_API_KEY}":
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "Unauthorized. Set Authorization: Bearer <WEB_API_KEY> header."})
        return await call_next(request)


app = FastAPI(title="AIHawk Jobs Applier", version="2.0.0")
app.add_middleware(_OptionalAuthMiddleware)

# In-memory job store for generated documents (max 100 entries, oldest evicted)
_jobs: dict = {}
_MAX_JOBS = 100

# Serialize generation requests so concurrent jobs don't clobber the global
# LLM config (cfg.LLM_MODEL_TYPE / cfg.LLM_MODEL) that the resume builder reads.
_generation_lock = asyncio.Lock()


def _cleanup_jobs() -> None:
    """Evict oldest completed/failed jobs when the store exceeds _MAX_JOBS."""
    if len(_jobs) <= _MAX_JOBS:
        return
    # Sort by insertion order (dict preserves it in Python 3.7+), remove oldest completed/failed first
    removable = [
        jid for jid, j in _jobs.items()
        if j.get("status") in ("completed", "failed")
    ]
    while len(_jobs) > _MAX_JOBS and removable:
        del _jobs[removable.pop(0)]


# Credentials file path
CREDENTIALS_PATH = Path("data_folder/credentials.yaml")

# ---------------------------------------------------------------------------
# Persistent generation history (SQLite)
# ---------------------------------------------------------------------------
_GEN_DB_PATH = Path("data_folder/applications.db")


def _init_gen_table() -> None:
    """Create the generation_history table if it doesn't exist."""
    import sqlite3
    _GEN_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_GEN_DB_PATH), timeout=10)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS generation_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id     TEXT NOT NULL,
            action     TEXT NOT NULL,
            status     TEXT NOT NULL,
            style      TEXT,
            job_url    TEXT,
            created_at TEXT NOT NULL,
            error      TEXT
        )
    """)
    conn.commit()
    conn.close()


def _persist_generation(job_id: str, action: str, status: str,
                        style: str = "", job_url: str = "", error: str = "") -> None:
    """Save a completed/failed generation to the persistent DB."""
    import sqlite3
    from datetime import datetime, timezone
    try:
        conn = sqlite3.connect(str(_GEN_DB_PATH), timeout=10)
        conn.execute(
            """INSERT INTO generation_history (job_id, action, status, style, job_url, created_at, error)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (job_id, action, status, style, job_url,
             datetime.now(timezone.utc).isoformat(), error),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning(f"Failed to persist generation history: {exc}")


# Initialize table on import
try:
    _init_gen_table()
except Exception:
    pass


class GenerateRequest(BaseModel):
    """Request model for document generation."""
    action: str  # "resume", "resume_tailored", "cover_letter"
    resume_yaml: str
    job_url: Optional[str] = None
    style: Optional[str] = None
    llm_api_key: str = ""  # Falls back to LLM_API_KEY env var when empty
    llm_model_type: str = "claude"
    llm_model: str = "claude-sonnet-4-6"


class JobStatus(BaseModel):
    """Status of a generation job."""
    job_id: str
    status: str  # "pending", "running", "completed", "failed"
    progress: int  # 0-100
    message: str
    download_url: Optional[str] = None
    error: Optional[str] = None


class ExperienceLevelModel(BaseModel):
    internship: bool = False
    entry: bool = True
    associate: bool = True
    mid_senior_level: bool = True
    director: bool = False
    executive: bool = False


class JobTypesModel(BaseModel):
    full_time: bool = True
    contract: bool = False
    part_time: bool = False
    temporary: bool = True
    internship: bool = False
    other: bool = False
    volunteer: bool = True


class DateFiltersModel(BaseModel):
    all_time: bool = False
    month: bool = False
    week: bool = False
    twenty_four_hours: bool = True

    class Config:
        populate_by_name = True

    @classmethod
    def from_yaml_dict(cls, data: dict) -> "DateFiltersModel":
        return cls(
            all_time=data.get("all_time", False),
            month=data.get("month", False),
            week=data.get("week", False),
            twenty_four_hours=data.get("24_hours", True),
        )

    def to_yaml_dict(self) -> dict:
        return {
            "all_time": self.all_time,
            "month": self.month,
            "week": self.week,
            "24_hours": self.twenty_four_hours,
        }


class WorkPreferences(BaseModel):
    remote: bool = True
    hybrid: bool = True
    onsite: bool = True
    experience_level: ExperienceLevelModel = ExperienceLevelModel()
    job_types: JobTypesModel = JobTypesModel()
    date: DateFiltersModel = DateFiltersModel()
    positions: list[str] = ["Software engineer"]
    locations: list[str] = ["Germany"]
    apply_once_at_company: bool = True
    distance: int = 100
    company_blacklist: list[str] = ["wayfair", "Crossover"]
    title_blacklist: list[str] = ["word1", "word2"]
    location_blacklist: list[str] = ["Brazil"]

    @classmethod
    def from_yaml_dict(cls, data: dict) -> "WorkPreferences":
        date_data = data.get("date", {})
        date_model = DateFiltersModel.from_yaml_dict(date_data) if isinstance(date_data, dict) else DateFiltersModel()
        return cls(
            remote=data.get("remote", True),
            hybrid=data.get("hybrid", True),
            onsite=data.get("onsite", True),
            experience_level=ExperienceLevelModel(**data["experience_level"]) if "experience_level" in data else ExperienceLevelModel(),
            job_types=JobTypesModel(**data["job_types"]) if "job_types" in data else JobTypesModel(),
            date=date_model,
            positions=data.get("positions", ["Software engineer"]),
            locations=data.get("locations", ["Germany"]),
            apply_once_at_company=data.get("apply_once_at_company", True),
            distance=data.get("distance", 100),
            company_blacklist=data.get("company_blacklist") or [],
            title_blacklist=data.get("title_blacklist") or [],
            location_blacklist=data.get("location_blacklist") or [],
        )

    def to_yaml_dict(self) -> dict:
        return {
            "remote": self.remote,
            "hybrid": self.hybrid,
            "onsite": self.onsite,
            "experience_level": self.experience_level.model_dump(),
            "job_types": self.job_types.model_dump(),
            "date": self.date.to_yaml_dict(),
            "positions": self.positions,
            "locations": self.locations,
            "apply_once_at_company": self.apply_once_at_company,
            "distance": self.distance,
            "company_blacklist": self.company_blacklist,
            "title_blacklist": self.title_blacklist,
            "location_blacklist": self.location_blacklist,
        }


class ResumeUpdate(BaseModel):
    resume_yaml: str


DATA_FOLDER = Path("data_folder")
WORK_PREFERENCES_PATH = DATA_FOLDER / "work_preferences.yaml"
PLAIN_TEXT_RESUME_PATH = DATA_FOLDER / "plain_text_resume.yaml"

APPROVED_DISTANCES = {0, 5, 10, 25, 50, 100}


def _validate_work_preferences(data: dict) -> list[str]:
    """Validate work preferences dict using the same rules as ConfigValidator."""
    errors = []

    # Validate experience levels are booleans
    exp = data.get("experience_level", {})
    if not isinstance(exp, dict):
        errors.append("experience_level must be a dict")
    else:
        for level in ["internship", "entry", "associate", "mid_senior_level", "director", "executive"]:
            if level in exp and not isinstance(exp[level], bool):
                errors.append(f"Experience level '{level}' must be a boolean")

    # Validate job types are booleans
    jt = data.get("job_types", {})
    if not isinstance(jt, dict):
        errors.append("job_types must be a dict")
    else:
        for job_type in ["full_time", "contract", "part_time", "temporary", "internship", "other", "volunteer"]:
            if job_type in jt and not isinstance(jt[job_type], bool):
                errors.append(f"Job type '{job_type}' must be a boolean")

    # Validate date filters are booleans
    date = data.get("date", {})
    if not isinstance(date, dict):
        errors.append("date must be a dict")
    else:
        for df in ["all_time", "month", "week", "24_hours"]:
            if df in date and not isinstance(date[df], bool):
                errors.append(f"Date filter '{df}' must be a boolean")

    # Validate positions and locations are lists of strings
    for key in ["positions", "locations"]:
        val = data.get(key, [])
        if not isinstance(val, list) or not all(isinstance(item, str) for item in val):
            errors.append(f"'{key}' must be a list of strings")

    # Validate distance
    dist = data.get("distance")
    if dist not in APPROVED_DISTANCES:
        errors.append(f"distance must be one of {sorted(APPROVED_DISTANCES)}")

    # Validate blacklists are lists
    for bl in ["company_blacklist", "title_blacklist", "location_blacklist"]:
        val = data.get(bl)
        if val is None:
            continue
        if not isinstance(val, list):
            errors.append(f"'{bl}' must be a list")

    return errors


# WebSocket connection manager
class ConnectionManager:
    """Manages WebSocket connections for real-time progress updates."""

    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, job_id: str):
        await websocket.accept()
        if job_id not in self.active_connections:
            self.active_connections[job_id] = []
        self.active_connections[job_id].append(websocket)

    def disconnect(self, websocket: WebSocket, job_id: str):
        if job_id in self.active_connections:
            self.active_connections[job_id] = [
                ws for ws in self.active_connections[job_id] if ws != websocket
            ]
            if not self.active_connections[job_id]:
                del self.active_connections[job_id]

    async def send_progress(self, job_id: str, data: dict):
        if job_id in self.active_connections:
            disconnected = []
            for ws in self.active_connections[job_id]:
                try:
                    await ws.send_json(data)
                except Exception:
                    disconnected.append(ws)
            for ws in disconnected:
                self.disconnect(ws, job_id)


manager = ConnectionManager()


def _get_available_styles() -> dict:
    """Get available resume styles from the styles directory."""
    styles_dir = Path(__file__).resolve().parent.parent / "libs" / "resume_and_cover_builder" / "resume_style"
    styles = {}
    if not styles_dir.is_dir():
        return styles
    for file_path in styles_dir.iterdir():
        if file_path.is_file() and file_path.suffix == ".css":
            try:
                with file_path.open("r", encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line.startswith("/*") and first_line.endswith("*/"):
                        content = first_line[2:-2].strip()
                        if "$" in content:
                            style_name, author_link = content.split("$", 1)
                            styles[style_name.strip()] = (file_path.name, author_link.strip())
            except Exception:
                continue
    return styles


def _validate_resume_yaml(yaml_str: str) -> str | None:
    """Validate that the YAML string is a valid resume.

    Returns None on success, or a human-readable error string.
    """
    try:
        data = yaml.safe_load(yaml_str)
    except yaml.YAMLError as exc:
        return f"Invalid YAML syntax: {exc}"

    if not isinstance(data, dict):
        return "Resume YAML must be a mapping (key: value), not a list or scalar."

    if "personal_information" not in data:
        return "Missing required section 'personal_information'."

    pi = data["personal_information"]
    if not isinstance(pi, dict):
        return "'personal_information' must be a mapping with name, email, etc."
    if not pi.get("name") and not pi.get("surname"):
        return "Resume must include at least a name under 'personal_information'."

    return None


async def _run_generation(job_id: str, request: GenerateRequest):
    """Run document generation in a background thread with progress updates."""
    import config as cfg

    # Acquire lock so concurrent generation requests don't overwrite each
    # other's global LLM config (the resume builder reads cfg.LLM_MODEL_TYPE).
    async with _generation_lock:
        orig_type, orig_model = cfg.LLM_MODEL_TYPE, cfg.LLM_MODEL
        try:
            cfg.LLM_MODEL_TYPE = request.llm_model_type
            cfg.LLM_MODEL = request.llm_model

            _jobs[job_id]["status"] = "running"
            await manager.send_progress(job_id, {
                "status": "running", "progress": 5, "message": "Initializing..."
            })

            # Validate resume YAML
            resume_error = _validate_resume_yaml(request.resume_yaml)
            if resume_error:
                raise ValueError(f"Invalid resume YAML: {resume_error}")

            await manager.send_progress(job_id, {
                "status": "running", "progress": 10, "message": "Loading resume data..."
            })

            # Import here to avoid circular imports
            from src.libs.resume_and_cover_builder import ResumeFacade, ResumeGenerator, StyleManager
            from src.resume_schemas.resume import Resume

            # Parse resume
            resume_object = Resume(request.resume_yaml)

            await manager.send_progress(job_id, {
                "status": "running", "progress": 15, "message": "Setting up style..."
            })

            # Setup style
            style_manager = StyleManager()
            available_styles = style_manager.get_styles()
            if request.style and request.style in available_styles:
                style_manager.set_selected_style(request.style)
            elif available_styles:
                # Default to first available style
                first_style = next(iter(available_styles))
                style_manager.set_selected_style(first_style)
            else:
                raise ValueError("No resume styles available.")

            await manager.send_progress(job_id, {
                "status": "running", "progress": 20, "message": "Initializing resume generator..."
            })

            # Setup generator
            resume_generator = ResumeGenerator()
            resume_generator.set_resume_object(resume_object)

            output_path = Path("data_folder/output")
            output_path.mkdir(parents=True, exist_ok=True)

            resume_facade = ResumeFacade(
                api_key=request.llm_api_key,
                style_manager=style_manager,
                resume_generator=resume_generator,
                resume_object=resume_object,
                output_path=output_path,
            )

            if request.action in ("resume_tailored", "cover_letter"):
                if not request.job_url:
                    raise ValueError("Job URL is required for tailored documents.")

                await manager.send_progress(job_id, {
                    "status": "running", "progress": 25, "message": "Fetching job description..."
                })

                # Fetch job description using httpx instead of Selenium
                result_base64 = await asyncio.to_thread(
                    _generate_with_job_url, resume_facade, request
                )
            else:
                await manager.send_progress(job_id, {
                    "status": "running", "progress": 30, "message": "Generating resume with AI..."
                })
                result_base64 = await asyncio.to_thread(
                    _generate_base_resume, resume_facade
                )

            await manager.send_progress(job_id, {
                "status": "running", "progress": 90, "message": "Finalizing PDF..."
            })

            # Store result
            if isinstance(result_base64, tuple):
                pdf_data = base64.b64decode(result_base64[0])
            else:
                pdf_data = base64.b64decode(result_base64)

            _jobs[job_id]["pdf_data"] = pdf_data
            _jobs[job_id]["status"] = "completed"
            _jobs[job_id]["progress"] = 100

            filename = _get_filename(request.action, request.job_url)
            _jobs[job_id]["filename"] = filename

            await manager.send_progress(job_id, {
                "status": "completed",
                "progress": 100,
                "message": "Document generated successfully!",
                "download_url": f"/api/download/{job_id}",
            })
            _persist_generation(job_id, request.action, "completed",
                                style=request.style or "", job_url=request.job_url or "")

        except Exception as e:
            logger.error(f"Generation failed for job {job_id}: {e}")
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = str(e)
            await manager.send_progress(job_id, {
                "status": "failed", "progress": 0, "message": f"Error: {e}",
                "error": str(e),
            })
            _persist_generation(job_id, request.action, "failed",
                                style=request.style or "", job_url=request.job_url or "",
                                error=str(e))
        finally:
            cfg.LLM_MODEL_TYPE = orig_type
            cfg.LLM_MODEL = orig_model


def _generate_with_job_url(resume_facade: "ResumeFacade", request: GenerateRequest):
    """Generate a document that requires a job URL (runs in thread)."""
    import httpx
    from src.libs.resume_and_cover_builder.llm.llm_job_parser import LLMParser
    from src.libs.resume_and_cover_builder.config import global_config
    from src.job import Job

    # Fetch job page HTML using httpx instead of Selenium
    try:
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            response = client.get(request.job_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            response.raise_for_status()
            body_html = response.text
    except httpx.HTTPError as e:
        raise RuntimeError(f"Failed to fetch job URL: {e}")

    # Parse job description using LLM
    llm_parser = LLMParser(api_key=global_config.API_KEY)
    llm_parser.set_body_html(body_html)

    job = Job()
    job.role = llm_parser.extract_role()
    job.company = llm_parser.extract_company_name()
    job.description = llm_parser.extract_job_description()
    job.location = llm_parser.extract_location()
    job.link = request.job_url

    resume_facade.job = job
    resume_facade.llm_job_parser = llm_parser

    if request.action == "cover_letter":
        # Generate cover letter HTML
        style_path = resume_facade.style_manager.get_style_path()
        if style_path is None:
            raise ValueError("You must choose a style before generating the PDF.")
        cover_letter_html = resume_facade.resume_generator.create_cover_letter_job_description(
            style_path, job.description
        )
        return _html_to_pdf_without_selenium(cover_letter_html)
    else:
        # Generate tailored resume HTML
        style_path = resume_facade.style_manager.get_style_path()
        if style_path is None:
            raise ValueError("You must choose a style before generating the PDF.")
        html_resume = resume_facade.resume_generator.create_resume_job_description_text(
            style_path, job.description
        )
        return _html_to_pdf_without_selenium(html_resume)


def _generate_base_resume(resume_facade: "ResumeFacade"):
    """Generate a base resume (runs in thread)."""
    style_path = resume_facade.style_manager.get_style_path()
    if style_path is None:
        raise ValueError("You must choose a style before generating the PDF.")
    html_resume = resume_facade.resume_generator.create_resume(style_path)
    return _html_to_pdf_without_selenium(html_resume)


def _html_to_pdf_without_selenium(html_content: str) -> str:
    """
    Convert HTML to PDF without requiring Selenium/Chrome.
    Uses reportlab as a fallback, or returns base64-encoded HTML wrapped as PDF.
    For Railway deployment, we generate a simple PDF from HTML content.
    """
    try:
        # Try using Chrome headless if available (e.g., in Docker)
        from src.utils.chrome_utils import init_browser, HTML_to_PDF
        driver = init_browser()
        try:
            result = HTML_to_PDF(html_content, driver)
            return result
        finally:
            try:
                driver.quit()
            except Exception:
                pass
    except Exception:
        # Fallback: use reportlab to create a basic PDF
        logger.warning("Chrome not available, using reportlab PDF fallback")
        return _reportlab_pdf_from_html(html_content)


def _reportlab_pdf_from_html(html_content: str) -> str:
    """Create a PDF from HTML content using reportlab as fallback."""
    import io
    import re
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            topMargin=0.75 * inch, bottomMargin=0.75 * inch,
                            leftMargin=0.75 * inch, rightMargin=0.75 * inch)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Title'], fontSize=16, spaceAfter=12)
    heading_style = ParagraphStyle('CustomHeading', parent=styles['Heading2'], fontSize=12, spaceAfter=6)
    body_style = ParagraphStyle('CustomBody', parent=styles['Normal'], fontSize=10, spaceAfter=4)

    story = []

    # Strip HTML tags for simple text extraction (case-insensitive for safety)
    text = re.sub(r'<style[^>]*>.*?</style\s*>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<script[^>]*>.*?</script\s*>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Extract sections
    sections = re.split(r'<(?:h[12]|section)[^>]*>', text)
    for section in sections:
        # Clean HTML tags
        clean = re.sub(r'<[^>]+>', ' ', section)
        clean = re.sub(r'\s+', ' ', clean).strip()
        if clean:
            # Check if it looks like a heading
            if len(clean) < 50 and not clean.endswith('.'):
                story.append(Paragraph(clean, heading_style))
                story.append(Spacer(1, 4))
            else:
                # Split into paragraphs
                for para in clean.split('  '):
                    para = para.strip()
                    if para:
                        try:
                            story.append(Paragraph(para, body_style))
                        except (ValueError, AttributeError):
                            # If reportlab can't parse the markup, sanitize and retry
                            story.append(Paragraph(re.sub(r'[<>&]', '', para), body_style))
                        story.append(Spacer(1, 2))

    if not story:
        story.append(Paragraph("Document generated by AIHawk", body_style))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    return base64.b64encode(pdf_bytes).decode("utf-8")


def _get_filename(action: str, job_url: Optional[str] = None) -> str:
    """Generate a filename for the document.

    Note: MD5 is used only for filename uniqueness, not for cryptographic security.
    """
    if action == "resume":
        return "resume_base.pdf"
    elif action == "resume_tailored":
        suffix = hashlib.md5(job_url.encode()).hexdigest()[:8] if job_url else "tailored"
        return f"resume_tailored_{suffix}.pdf"
    else:
        suffix = hashlib.md5(job_url.encode()).hexdigest()[:8] if job_url else "cover"
        return f"cover_letter_{suffix}.pdf"


# === API Routes ===

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main web UI."""
    from src.web.ui import get_html
    return HTMLResponse(content=get_html())


@app.get("/api/health")
async def health():
    """Health check endpoint. Also reports which required data_folder files are missing."""
    import config as cfg
    required_files = {
        "plain_text_resume.yaml": Path("data_folder/plain_text_resume.yaml"),
        "work_preferences.yaml": Path("data_folder/work_preferences.yaml"),
    }
    # secrets.yaml is only required when LLM_API_KEY env var is not set
    if not cfg.LLM_API_KEY:
        required_files["secrets.yaml"] = Path("data_folder/secrets.yaml")

    missing = [name for name, path in required_files.items() if not path.exists()]
    return {
        "status": "ok",
        "version": "2.0.0",
        "data_folder_ready": len(missing) == 0,
        "missing_files": missing,
    }


@app.get("/api/config")
async def get_config():
    """Expose non-secret configuration to the frontend.

    Tells the UI whether an API key is available via env var so the
    API-key input field can be made optional.
    """
    import config as cfg
    return {
        "llm_api_key_configured": bool(cfg.LLM_API_KEY),
        "llm_model_type": cfg.LLM_MODEL_TYPE,
        "llm_model": cfg.LLM_MODEL,
        "linkedin_configured": bool(cfg.LINKEDIN_EMAIL and cfg.LINKEDIN_PASSWORD),
    }


@app.get("/api/generation-history")
async def get_generation_history(limit: int = 50):
    """Return recent document generation history from the persistent DB."""
    import sqlite3
    try:
        conn = sqlite3.connect(str(_GEN_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM generation_history ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return {"history": [dict(r) for r in rows]}
    except Exception as exc:
        return {"history": [], "error": str(exc)}


@app.get("/api/styles")
async def get_styles():
    """Get available resume styles."""
    try:
        styles = _get_available_styles()
        return {
            "styles": [
                {"name": name, "file": file_name, "author": author}
                for name, (file_name, author) in styles.items()
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load styles: {e}")


@app.post("/api/generate")
async def generate_document(request: GenerateRequest):
    """Start async document generation. Returns a job ID for tracking progress."""
    # Validate request
    if request.action not in ("resume", "resume_tailored", "cover_letter"):
        raise HTTPException(status_code=400, detail="Invalid action. Must be 'resume', 'resume_tailored', or 'cover_letter'.")

    # Fall back to env var if no API key provided in request
    import config as cfg
    if not request.llm_api_key and cfg.LLM_API_KEY:
        request.llm_api_key = cfg.LLM_API_KEY

    if not request.llm_api_key:
        raise HTTPException(status_code=400, detail="LLM API key is required. Set LLM_API_KEY env var or provide it in the request.")

    if not request.resume_yaml.strip():
        raise HTTPException(status_code=400, detail="Resume YAML is required.")

    if request.action in ("resume_tailored", "cover_letter") and not request.job_url:
        raise HTTPException(status_code=400, detail="Job URL is required for tailored documents.")

    # Ensure data_folder exists for generation artifacts
    DATA_FOLDER.mkdir(parents=True, exist_ok=True)

    # Create job (evict old entries if needed)
    _cleanup_jobs()
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "message": "Job queued",
        "pdf_data": None,
        "filename": None,
        "error": None,
    }

    # Start async generation
    asyncio.create_task(_run_generation(job_id, request))

    return {"job_id": job_id, "status": "pending", "ws_url": f"/ws/{job_id}"}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    """Get the status of a generation job."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found.")
    job = _jobs[job_id]
    result = {
        "job_id": job_id,
        "status": job["status"],
        "progress": job.get("progress", 0),
        "message": job.get("message", ""),
    }
    if job["status"] == "completed":
        result["download_url"] = f"/api/download/{job_id}"
    if job["status"] == "failed":
        result["error"] = job.get("error", "Unknown error")
    return result


@app.get("/api/download/{job_id}")
async def download_document(job_id: str):
    """Download a generated document."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found.")
    job = _jobs[job_id]
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Document not ready yet.")
    if not job.get("pdf_data"):
        raise HTTPException(status_code=500, detail="PDF data not available.")

    return Response(
        content=job["pdf_data"],
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{job.get("filename", "document.pdf")}"'
        },
    )


@app.get("/api/preferences")
async def get_preferences():
    """Load work preferences from data_folder/work_preferences.yaml."""
    if WORK_PREFERENCES_PATH.exists():
        try:
            with open(WORK_PREFERENCES_PATH, "r") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                raise HTTPException(status_code=500, detail="Invalid work_preferences.yaml format.")
            prefs = WorkPreferences.from_yaml_dict(data)
        except yaml.YAMLError as exc:
            raise HTTPException(status_code=500, detail=f"Error parsing work_preferences.yaml: {exc}")
    else:
        prefs = WorkPreferences()
    return prefs.to_yaml_dict()


@app.put("/api/preferences")
async def update_preferences(prefs: WorkPreferences):
    """Save work preferences to data_folder/work_preferences.yaml."""
    yaml_dict = prefs.to_yaml_dict()

    errors = _validate_work_preferences(yaml_dict)
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    DATA_FOLDER.mkdir(parents=True, exist_ok=True)
    try:
        with open(WORK_PREFERENCES_PATH, "w") as f:
            yaml.dump(yaml_dict, f, default_flow_style=False, sort_keys=False)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save preferences: {exc}")
    return {"status": "ok", "message": "Work preferences saved."}


@app.get("/api/resume")
async def get_resume():
    """Load plain text resume YAML from data_folder/plain_text_resume.yaml."""
    if PLAIN_TEXT_RESUME_PATH.exists():
        try:
            content = PLAIN_TEXT_RESUME_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Error reading resume file: {exc}")
    else:
        example_path = Path("data_folder_example") / "plain_text_resume.yaml"
        if example_path.exists():
            content = example_path.read_text(encoding="utf-8")
        else:
            content = "personal_information:\n  name: \"\"\n  surname: \"\"\n"
    return {"resume_yaml": content}


@app.put("/api/resume")
async def update_resume(body: ResumeUpdate):
    """Save plain text resume YAML to data_folder/plain_text_resume.yaml."""
    if not body.resume_yaml.strip():
        raise HTTPException(status_code=400, detail="Resume YAML content cannot be empty.")

    resume_error = _validate_resume_yaml(body.resume_yaml)
    if resume_error:
        raise HTTPException(status_code=422, detail=f"Invalid resume YAML: {resume_error}")

    DATA_FOLDER.mkdir(parents=True, exist_ok=True)
    try:
        PLAIN_TEXT_RESUME_PATH.write_text(body.resume_yaml, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save resume: {exc}")
    return {"status": "ok", "message": "Resume saved."}


def _extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract text content from a PDF file using pdfminer."""
    import io
    from pdfminer.high_level import extract_text

    return extract_text(io.BytesIO(pdf_bytes))


_CV_PARSE_PROMPT = """\
You are a resume/CV parser. Given the text extracted from a PDF resume below, \
produce a YAML document that exactly follows this schema. Output ONLY valid YAML — \
no markdown fences, no commentary, no explanation.

Schema:
```
personal_information:
  name: ""
  surname: ""
  date_of_birth: ""
  country: ""
  city: ""
  zip_code: ""
  address: ""
  phone_prefix: ""
  phone: ""
  email: ""
  github: ""
  linkedin: ""

education_details:
  - education_level: ""
    institution: ""
    field_of_study: ""
    final_evaluation_grade: ""
    start_date: ""
    year_of_completion: ""

experience_details:
  - position: ""
    company: ""
    employment_period: ""
    location: ""
    industry: ""
    key_responsibilities:
      - responsibility: ""
    skills_acquired:
      - ""

projects:
  - name: ""
    description: ""
    link: ""

achievements:
  - name: ""
    description: ""

certifications:
  - name: ""
    description: ""

languages:
  - language: ""
    proficiency: ""

interests:
  - ""

availability:
  notice_period: ""

salary_expectations:
  salary_range_usd: ""

self_identification:
  gender: ""
  pronouns: ""
  veteran: ""
  disability: ""
  ethnicity: ""

legal_authorization:
  eu_work_authorization: ""
  us_work_authorization: ""
  requires_us_visa: ""
  requires_us_sponsorship: ""
  requires_eu_visa: ""
  legally_allowed_to_work_in_eu: ""
  legally_allowed_to_work_in_us: ""
  requires_eu_sponsorship: ""
  canada_work_authorization: ""
  requires_canada_visa: ""
  legally_allowed_to_work_in_canada: ""
  requires_canada_sponsorship: ""
  uk_work_authorization: ""
  requires_uk_visa: ""
  legally_allowed_to_work_in_uk: ""
  requires_uk_sponsorship: ""

work_preferences:
  remote_work: ""
  in_person_work: ""
  open_to_relocation: ""
  willing_to_complete_assessments: ""
  willing_to_undergo_drug_tests: ""
  willing_to_undergo_background_checks: ""
```

Rules:
- Fill in every field you can find evidence for in the resume text.
- For fields not found in the resume, use an empty string "".
- For education_details, experience_details, projects, achievements, certifications, and languages, include all entries found.
- For URLs (github, linkedin), include only if explicitly present in the text.
- phone_prefix should be the international dialing code (e.g. "+1", "+44").
- employment_period format: "MM/YYYY - MM/YYYY" or "MM/YYYY - Present".
- year_of_completion should be an integer year.
- Keep self_identification and legal_authorization fields as empty strings unless explicitly stated.
- Do NOT invent or hallucinate information that is not in the resume text.

After the YAML, on a new line output exactly one line starting with "INFERRED_PREFERENCES:" followed by a JSON object \
with keys "positions" (list of job titles this person would target) and "locations" (list of cities/countries from their experience). \
Base these ONLY on evidence in the resume. Example:
INFERRED_PREFERENCES:{{"positions":["Software Engineer","Backend Developer"],"locations":["San Francisco","USA"]}}

Resume text:
{pdf_text}"""


def _parse_cv_with_llm(pdf_text: str, api_key: str) -> tuple[str, dict]:
    """Send extracted CV text to LLM and return (resume_yaml, inferred_preferences)."""
    import json
    import config as cfg
    from src.libs.resume_and_cover_builder.llm.llm_factory import create_chat_model
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    llm = create_chat_model(api_key)
    prompt = ChatPromptTemplate.from_template(_CV_PARSE_PROMPT)
    chain = prompt | llm | StrOutputParser()
    raw_output = chain.invoke({"pdf_text": pdf_text})

    # Split YAML from inferred preferences line
    resume_yaml = raw_output
    inferred = {"positions": [], "locations": []}

    lines = raw_output.strip().split("\n")
    yaml_lines = []
    for line in lines:
        if line.startswith("INFERRED_PREFERENCES:"):
            try:
                inferred = json.loads(line[len("INFERRED_PREFERENCES:"):].strip())
            except (json.JSONDecodeError, ValueError):
                pass
        else:
            yaml_lines.append(line)

    resume_yaml = "\n".join(yaml_lines).strip()

    # Strip markdown fences if the LLM added them despite instructions
    if resume_yaml.startswith("```"):
        first_newline = resume_yaml.index("\n") if "\n" in resume_yaml else 3
        resume_yaml = resume_yaml[first_newline + 1:]
    if resume_yaml.endswith("```"):
        resume_yaml = resume_yaml[:-3].rstrip()

    return resume_yaml, inferred


@app.post("/api/resume/upload-pdf")
async def upload_pdf_resume(
    file: UploadFile = File(...),
    llm_api_key: str = Form(""),
    llm_model_type: str = Form("claude"),
    llm_model: str = Form("claude-sonnet-4-6"),
):
    """Upload a PDF resume, extract text, and use LLM to generate resume YAML."""
    import config as cfg

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    # Resolve API key
    api_key = llm_api_key or cfg.LLM_API_KEY
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="LLM API key is required. Configure it in Step 1 or set the LLM_API_KEY environment variable.",
        )

    # Acquire lock so concurrent requests don't overwrite each other's model config
    async with _generation_lock:
        orig_type, orig_model = cfg.LLM_MODEL_TYPE, cfg.LLM_MODEL
        cfg.LLM_MODEL_TYPE = llm_model_type
        cfg.LLM_MODEL = llm_model

        try:
            return await _upload_pdf_inner(file, api_key)
        finally:
            cfg.LLM_MODEL_TYPE = orig_type
            cfg.LLM_MODEL = orig_model


async def _upload_pdf_inner(file: UploadFile, api_key: str):
    # Read and extract text from PDF
    pdf_bytes = await file.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        pdf_text = await asyncio.to_thread(_extract_text_from_pdf, pdf_bytes)
    except Exception as e:
        logger.error(f"PDF text extraction failed: {e}")
        raise HTTPException(status_code=422, detail=f"Failed to extract text from PDF: {e}")

    if not pdf_text.strip():
        raise HTTPException(
            status_code=422,
            detail="Could not extract any text from the PDF. The file may be image-based or empty.",
        )

    # Parse with LLM
    try:
        resume_yaml, inferred = await asyncio.to_thread(_parse_cv_with_llm, pdf_text, api_key)
    except Exception as e:
        logger.error(f"LLM CV parsing failed: {e}")
        raise HTTPException(status_code=500, detail=f"AI parsing failed: {e}")

    return {
        "resume_yaml": resume_yaml,
        "inferred_preferences": inferred,
    }


@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time progress updates."""
    await manager.connect(websocket, job_id)
    try:
        # Send current status immediately
        if job_id in _jobs:
            job = _jobs[job_id]
            await websocket.send_json({
                "status": job["status"],
                "progress": job.get("progress", 0),
                "message": job.get("message", ""),
            })

        # Keep connection alive
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        manager.disconnect(websocket, job_id)


# =============================================================================
# Bot Control Endpoints
# =============================================================================

class BotStartRequest(BaseModel):
    """Request body for POST /api/bot/start."""
    platforms: list[str] = ["linkedin"]
    min_score: int = 7
    max_applications: int = 50
    headless: bool = True
    generate_tailored_resume: bool = False
    llm_api_key: str = ""  # Falls back to LLM_API_KEY env var when empty
    llm_model_type: str = "claude"
    llm_model: str = "claude-sonnet-4-6"


class CredentialsUpdate(BaseModel):
    """Per-platform login credentials."""
    linkedin: Optional[dict] = None       # {email, password}
    indeed: Optional[dict] = None
    glassdoor: Optional[dict] = None
    ziprecruiter: Optional[dict] = None
    dice: Optional[dict] = None


def _load_credentials() -> dict:
    """Load credentials.yaml, return empty dict if not found."""
    if CREDENTIALS_PATH.exists():
        try:
            return yaml.safe_load(CREDENTIALS_PATH.read_text()) or {}
        except Exception:
            return {}
    return {}


def _save_credentials(data: dict) -> None:
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def _load_preferences() -> dict:
    if WORK_PREFERENCES_PATH.exists():
        try:
            return yaml.safe_load(WORK_PREFERENCES_PATH.read_text()) or {}
        except Exception:
            return {}
    return {}


# Bot WebSocket connections store
_bot_connections: list[WebSocket] = []


@app.post("/api/bot/start")
async def bot_start(request: BotStartRequest):
    """Start the automation bot."""
    import config as _cfg
    from src.automation.bot_manager import BotManager, BotConfig
    bot = BotManager()
    if bot.status == "running":
        raise HTTPException(status_code=409, detail="Bot is already running.")

    # Fall back to env var if no API key provided in request
    if not request.llm_api_key and _cfg.LLM_API_KEY:
        request.llm_api_key = _cfg.LLM_API_KEY
    if not request.llm_api_key:
        raise HTTPException(status_code=400, detail="LLM API key is required. Set LLM_API_KEY env var or provide it in the request.")

    credentials = _load_credentials()

    # Overlay env-var credentials for LinkedIn (Railway convenience)
    if _cfg.LINKEDIN_EMAIL and _cfg.LINKEDIN_PASSWORD:
        credentials.setdefault("linkedin", {})
        credentials["linkedin"].setdefault("email", _cfg.LINKEDIN_EMAIL)
        credentials["linkedin"].setdefault("password", _cfg.LINKEDIN_PASSWORD)

    preferences = _load_preferences()

    creds_by_platform = {}
    for platform in request.platforms:
        creds_by_platform[platform] = credentials.get(platform, {})

    config = BotConfig(
        platforms=request.platforms,
        credentials=creds_by_platform,
        preferences=preferences,
        llm_api_key=request.llm_api_key,
        llm_model_type=request.llm_model_type,
        llm_model=request.llm_model,
        min_score=request.min_score,
        max_applications=request.max_applications,
        headless=request.headless,
        generate_tailored_resume=request.generate_tailored_resume,
    )

    # Register a callback to push log entries to all connected bot WebSocket clients
    async def ws_broadcast(entry: dict):
        dead = []
        for ws in _bot_connections:
            try:
                await ws.send_json({"type": "log", **entry, **bot.get_status()})
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in _bot_connections:
                _bot_connections.remove(ws)

    bot.register_progress_callback(ws_broadcast)

    session_id = await bot.start(config)
    return {"status": "started", "session_id": session_id}


@app.post("/api/bot/stop")
async def bot_stop():
    """Stop the running bot."""
    from src.automation.bot_manager import BotManager
    bot = BotManager()
    await bot.stop()
    return {"status": "stopped"}


@app.post("/api/bot/pause")
async def bot_pause():
    """Pause the running bot."""
    from src.automation.bot_manager import BotManager
    bot = BotManager()
    await bot.pause()
    return {"status": "paused"}


@app.post("/api/bot/resume")
async def bot_resume():
    """Resume a paused bot."""
    from src.automation.bot_manager import BotManager
    bot = BotManager()
    await bot.resume()
    return {"status": "running"}


@app.get("/api/bot/status")
async def bot_status():
    """Get current bot status and stats."""
    from src.automation.bot_manager import BotManager
    bot = BotManager()
    return bot.get_status()


@app.websocket("/ws/bot")
async def bot_websocket(websocket: WebSocket):
    """WebSocket for real-time bot log streaming."""
    await websocket.accept()
    _bot_connections.append(websocket)
    try:
        # Send current status immediately
        from src.automation.bot_manager import BotManager
        bot = BotManager()
        await websocket.send_json({"type": "status", **bot.get_status()})
        # Keep alive — server pushes updates via ws_broadcast callback
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        if websocket in _bot_connections:
            _bot_connections.remove(websocket)


# =============================================================================
# Credentials Endpoints
# =============================================================================

@app.get("/api/credentials")
async def get_credentials():
    """Return saved credentials with passwords masked."""
    creds = _load_credentials()
    masked = {}
    for platform, data in creds.items():
        if isinstance(data, dict):
            masked[platform] = {
                k: ("***" if "password" in k.lower() or "secret" in k.lower() else v)
                for k, v in data.items()
            }
    return masked


@app.put("/api/credentials")
async def update_credentials(body: CredentialsUpdate):
    """Save credentials for each platform."""
    existing = _load_credentials()
    update_data = {
        k: v for k, v in body.model_dump().items() if v is not None
    }
    existing.update(update_data)
    try:
        _save_credentials(existing)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save credentials: {exc}")
    return {"status": "ok", "message": "Credentials saved."}


# =============================================================================
# Application History Endpoints
# =============================================================================

@app.get("/api/applications")
async def list_applications(
    platform: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
):
    """List job applications from the tracker database."""
    from src.automation.application_tracker import ApplicationTracker
    tracker = ApplicationTracker()
    apps = tracker.get_applications(platform=platform, status=status, limit=limit, offset=offset)
    stats = tracker.get_stats()
    return {"applications": apps, "stats": stats}


@app.get("/api/applications/{app_id}")
async def get_application(app_id: int):
    """Get a single application by ID."""
    from src.automation.application_tracker import ApplicationTracker
    tracker = ApplicationTracker()
    app = tracker.get_application(app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found.")
    return app


@app.get("/api/applications/export/csv")
async def export_applications_csv():
    """Export all applications as CSV."""
    from src.automation.application_tracker import ApplicationTracker
    tracker = ApplicationTracker()
    csv_data = tracker.export_csv()
    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=applications.csv"},
    )
