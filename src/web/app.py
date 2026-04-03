"""
FastAPI web server for AIHawk Resume & Cover Letter Builder.
Provides a web UI with async document generation and WebSocket progress updates.
"""
import asyncio
import base64
import hashlib
import os
import uuid
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from src.logging import logger

app = FastAPI(title="AIHawk Resume Builder", version="1.0.0")

# In-memory job store for generated documents
_jobs: dict = {}


class GenerateRequest(BaseModel):
    """Request model for document generation."""
    action: str  # "resume", "resume_tailored", "cover_letter"
    resume_yaml: str
    job_url: Optional[str] = None
    style: Optional[str] = None
    llm_api_key: str
    llm_model_type: str = "claude"
    llm_model: str = "claude-sonnet-4-20250514"


class JobStatus(BaseModel):
    """Status of a generation job."""
    job_id: str
    status: str  # "pending", "running", "completed", "failed"
    progress: int  # 0-100
    message: str
    download_url: Optional[str] = None
    error: Optional[str] = None


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
    from src.libs.resume_and_cover_builder.style_manager import StyleManager
    sm = StyleManager()
    return sm.get_styles()


def _validate_resume_yaml(yaml_str: str) -> bool:
    """Validate that the YAML string is a valid resume."""
    try:
        data = yaml.safe_load(yaml_str)
        if not isinstance(data, dict):
            return False
        if "personal_information" not in data:
            return False
        return True
    except yaml.YAMLError:
        return False


async def _run_generation(job_id: str, request: GenerateRequest):
    """Run document generation in a background thread with progress updates."""
    import config as cfg

    try:
        # Update config with user-selected LLM
        cfg.LLM_MODEL_TYPE = request.llm_model_type
        cfg.LLM_MODEL = request.llm_model

        _jobs[job_id]["status"] = "running"
        await manager.send_progress(job_id, {
            "status": "running", "progress": 5, "message": "Initializing..."
        })

        # Validate resume YAML
        if not _validate_resume_yaml(request.resume_yaml):
            raise ValueError("Invalid resume YAML. Must contain at least 'personal_information' section.")

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

    except Exception as e:
        logger.error(f"Generation failed for job {job_id}: {e}")
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(e)
        await manager.send_progress(job_id, {
            "status": "failed", "progress": 0, "message": f"Error: {e}",
            "error": str(e),
        })


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
    llm_parser = LLMParser(openai_api_key=global_config.API_KEY)
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

    # Strip HTML tags for simple text extraction
    text = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)

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
                        except Exception:
                            # If reportlab can't parse it, add as plain text
                            story.append(Paragraph(re.sub(r'[<>&]', '', para), body_style))
                        story.append(Spacer(1, 2))

    if not story:
        story.append(Paragraph("Document generated by AIHawk", body_style))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    return base64.b64encode(pdf_bytes).decode("utf-8")


def _get_filename(action: str, job_url: Optional[str] = None) -> str:
    """Generate a filename for the document."""
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
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}


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

    if not request.llm_api_key:
        raise HTTPException(status_code=400, detail="LLM API key is required.")

    if not request.resume_yaml.strip():
        raise HTTPException(status_code=400, detail="Resume YAML is required.")

    if request.action in ("resume_tailored", "cover_letter") and not request.job_url:
        raise HTTPException(status_code=400, detail="Job URL is required for tailored documents.")

    # Create job
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
