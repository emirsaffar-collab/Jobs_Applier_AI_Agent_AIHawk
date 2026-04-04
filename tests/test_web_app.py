"""
Tests for the FastAPI web application at src.web.app.

Uses httpx.AsyncClient with ASGITransport for async endpoint testing.
All tests run without the WEB_API_KEY env var set, so auth middleware is inactive.
"""

import pytest
import httpx

from src.web.app import app


@pytest.fixture
def async_client():
    """Provide an httpx.AsyncClient wired to the FastAPI app."""
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# 1. GET / returns HTML 200
@pytest.mark.asyncio
async def test_index_returns_html(async_client):
    async with async_client as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


# 2. GET /api/health returns {status: "ok"}
@pytest.mark.asyncio
async def test_health_returns_ok(async_client):
    async with async_client as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


# 3. GET /api/styles returns styles list
@pytest.mark.asyncio
async def test_styles_returns_list(async_client):
    async with async_client as client:
        response = await client.get("/api/styles")
    assert response.status_code == 200
    data = response.json()
    assert "styles" in data
    assert isinstance(data["styles"], list)


# 4. POST /api/generate validates action field (returns 400 for invalid)
@pytest.mark.asyncio
async def test_generate_invalid_action_returns_400(async_client):
    payload = {
        "action": "invalid_action",
        "resume_yaml": "personal_information:\n  name: Test\n",
        "llm_api_key": "test-key",
    }
    async with async_client as client:
        response = await client.post("/api/generate", json=payload)
    assert response.status_code == 400
    assert "Invalid action" in response.json()["detail"]


# 5. POST /api/generate returns 400 when no API key and model != ollama
@pytest.mark.asyncio
async def test_generate_no_api_key_non_ollama_returns_400(async_client, monkeypatch):
    # Ensure no env-var API key is set
    monkeypatch.setattr("src.web.app.os.environ", {})
    import config as cfg
    monkeypatch.setattr(cfg, "LLM_API_KEY", "")

    payload = {
        "action": "resume",
        "resume_yaml": "personal_information:\n  name: Test\n",
        "llm_api_key": "",
        "llm_model_type": "claude",
    }
    async with async_client as client:
        response = await client.post("/api/generate", json=payload)
    assert response.status_code == 400
    assert "API key" in response.json()["detail"]


# 6. GET /api/status/{job_id} returns 404 for unknown job
@pytest.mark.asyncio
async def test_status_unknown_job_returns_404(async_client):
    async with async_client as client:
        response = await client.get("/api/status/nonexistent-job-id")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# 7. GET /api/download/{job_id} returns 404 for unknown job
@pytest.mark.asyncio
async def test_download_unknown_job_returns_404(async_client):
    async with async_client as client:
        response = await client.get("/api/download/nonexistent-job-id")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# 8. GET /api/preferences returns valid preferences structure
@pytest.mark.asyncio
async def test_preferences_returns_valid_structure(async_client):
    async with async_client as client:
        response = await client.get("/api/preferences")
    assert response.status_code == 200
    data = response.json()
    # Should contain core preference keys
    assert "remote" in data
    assert "positions" in data
    assert "locations" in data
    assert "experience_level" in data
    assert "job_types" in data
    assert "date" in data
    assert "distance" in data
    assert isinstance(data["positions"], list)
    assert isinstance(data["locations"], list)


# 9. PUT /api/resume returns 400 for empty content
@pytest.mark.asyncio
async def test_resume_update_empty_returns_400(async_client):
    payload = {"resume_yaml": "   "}
    async with async_client as client:
        response = await client.put("/api/resume", json=payload)
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


# 10. PUT /api/preferences validates properly
@pytest.mark.asyncio
async def test_preferences_update_validates_distance(async_client):
    payload = {
        "remote": True,
        "hybrid": True,
        "onsite": True,
        "experience_level": {
            "internship": False,
            "entry": True,
            "associate": True,
            "mid_senior_level": True,
            "director": False,
            "executive": False,
        },
        "job_types": {
            "full_time": True,
            "contract": False,
            "part_time": False,
            "temporary": True,
            "internship": False,
            "other": False,
            "volunteer": True,
        },
        "date": {
            "all_time": False,
            "month": False,
            "week": False,
            "twenty_four_hours": True,
        },
        "positions": ["Software Engineer"],
        "locations": ["Remote"],
        "apply_once_at_company": True,
        "distance": 999,  # Invalid distance value
        "company_blacklist": [],
        "title_blacklist": [],
        "location_blacklist": [],
    }
    async with async_client as client:
        response = await client.put("/api/preferences", json=payload)
    assert response.status_code == 422
    # The validation error should mention distance
    detail = response.json()["detail"]
    if isinstance(detail, list):
        errors_text = str(detail)
    else:
        errors_text = str(detail)
    assert "distance" in errors_text.lower()
