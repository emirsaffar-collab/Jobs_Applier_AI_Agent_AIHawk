"""Tests for BasePlatform, JobListing, and ApplyResult in src.automation.platforms.base."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import TimeoutError as PWTimeout

from src.automation.platforms.base import ApplyResult, BasePlatform, JobListing


# ---------------------------------------------------------------------------
# Concrete subclass so we can instantiate the ABC
# ---------------------------------------------------------------------------

class _TestPlatform(BasePlatform):
    async def login(self, page, credentials, browser_manager=None) -> bool:
        return True

    async def search_jobs(self, page, preferences) -> list[JobListing]:
        return []

    async def apply_to_job(self, page, job, resume_path="", cover_letter_path="") -> ApplyResult:
        return ApplyResult()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def platform():
    return _TestPlatform(llm=None)


@pytest.fixture
def platform_with_llm():
    llm = MagicMock()
    return _TestPlatform(llm=llm)


@pytest.fixture
def mock_page():
    page = AsyncMock()
    return page


# ---------------------------------------------------------------------------
# JobListing dataclass
# ---------------------------------------------------------------------------

class TestJobListing:
    def test_required_fields(self):
        job = JobListing(
            title="Engineer",
            company="Acme",
            location="Remote",
            url="https://example.com/job/1",
        )
        assert job.title == "Engineer"
        assert job.company == "Acme"
        assert job.location == "Remote"
        assert job.url == "https://example.com/job/1"

    def test_defaults(self):
        job = JobListing(title="E", company="C", location="L", url="U")
        assert job.description == ""
        assert job.platform == ""
        assert job.job_id == ""
        assert job.apply_method == ""
        assert job.extra == {}

    def test_extra_is_independent_per_instance(self):
        j1 = JobListing(title="A", company="B", location="C", url="D")
        j2 = JobListing(title="A", company="B", location="C", url="D")
        j1.extra["key"] = "value"
        assert "key" not in j2.extra


# ---------------------------------------------------------------------------
# ApplyResult dataclass
# ---------------------------------------------------------------------------

class TestApplyResult:
    def test_defaults(self):
        r = ApplyResult()
        assert r.success is False
        assert r.skipped is False
        assert r.reason == ""

    def test_custom_values(self):
        r = ApplyResult(success=True, skipped=False, reason="applied")
        assert r.success is True
        assert r.reason == "applied"


# ---------------------------------------------------------------------------
# _human_delay
# ---------------------------------------------------------------------------

class TestHumanDelay:
    @pytest.mark.asyncio
    async def test_calls_asyncio_sleep(self, platform):
        with patch("src.automation.platforms.base.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await platform._human_delay(1.0, 2.0)
            mock_sleep.assert_awaited_once()
            delay = mock_sleep.call_args[0][0]
            assert 1.0 <= delay <= 2.0


# ---------------------------------------------------------------------------
# _safe_click
# ---------------------------------------------------------------------------

class TestSafeClick:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self, platform, mock_page):
        mock_page.click = AsyncMock()
        result = await platform._safe_click(mock_page, "#btn")
        assert result is True
        mock_page.click.assert_awaited_once_with("#btn", timeout=5000)

    @pytest.mark.asyncio
    async def test_retries_on_timeout_then_fails(self, platform, mock_page):
        mock_page.click = AsyncMock(side_effect=PWTimeout("timeout"))
        with patch("src.automation.platforms.base.asyncio.sleep", new_callable=AsyncMock):
            result = await platform._safe_click(mock_page, "#btn", retries=2)
        assert result is False
        assert mock_page.click.await_count == 3  # initial + 2 retries

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self, platform, mock_page):
        mock_page.click = AsyncMock(side_effect=[PWTimeout("t"), None])
        with patch("src.automation.platforms.base.asyncio.sleep", new_callable=AsyncMock):
            result = await platform._safe_click(mock_page, "#btn", retries=2)
        assert result is True
        assert mock_page.click.await_count == 2

    @pytest.mark.asyncio
    async def test_returns_false_on_unexpected_exception(self, platform, mock_page):
        mock_page.click = AsyncMock(side_effect=RuntimeError("boom"))
        result = await platform._safe_click(mock_page, "#btn")
        assert result is False


# ---------------------------------------------------------------------------
# _safe_fill
# ---------------------------------------------------------------------------

class TestSafeFill:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self, platform, mock_page):
        mock_page.fill = AsyncMock()
        result = await platform._safe_fill(mock_page, "#input", "hello")
        assert result is True
        mock_page.fill.assert_awaited_once_with("#input", "hello", timeout=5000)

    @pytest.mark.asyncio
    async def test_retries_on_timeout_then_fails(self, platform, mock_page):
        mock_page.fill = AsyncMock(side_effect=PWTimeout("timeout"))
        with patch("src.automation.platforms.base.asyncio.sleep", new_callable=AsyncMock):
            result = await platform._safe_fill(mock_page, "#input", "val", retries=2)
        assert result is False
        assert mock_page.fill.await_count == 3

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self, platform, mock_page):
        mock_page.fill = AsyncMock(side_effect=[PWTimeout("t"), None])
        with patch("src.automation.platforms.base.asyncio.sleep", new_callable=AsyncMock):
            result = await platform._safe_fill(mock_page, "#input", "val", retries=2)
        assert result is True
        assert mock_page.fill.await_count == 2

    @pytest.mark.asyncio
    async def test_returns_false_on_unexpected_exception(self, platform, mock_page):
        mock_page.fill = AsyncMock(side_effect=RuntimeError("boom"))
        result = await platform._safe_fill(mock_page, "#input", "val")
        assert result is False


# ---------------------------------------------------------------------------
# _answer_with_llm
# ---------------------------------------------------------------------------

class TestAnswerWithLlm:
    @pytest.mark.asyncio
    async def test_returns_first_option_when_llm_is_none(self, platform):
        result = await platform._answer_with_llm("Fav color?", ["Red", "Blue"])
        assert result == "Red"

    @pytest.mark.asyncio
    async def test_returns_yes_when_llm_is_none_and_no_options(self, platform):
        result = await platform._answer_with_llm("Tell me about yourself")
        assert result == "Yes"

    @pytest.mark.asyncio
    async def test_returns_llm_response_string(self, platform_with_llm):
        platform_with_llm._llm.invoke.return_value = "Blue"
        result = await platform_with_llm._answer_with_llm("Fav color?", ["Red", "Blue"])
        assert result == "Blue"

    @pytest.mark.asyncio
    async def test_returns_llm_response_with_content_attr(self, platform_with_llm):
        response = MagicMock()
        response.content = "  Blue  "
        platform_with_llm._llm.invoke.return_value = response
        result = await platform_with_llm._answer_with_llm("Fav color?", ["Red", "Blue"])
        assert result == "Blue"

    @pytest.mark.asyncio
    async def test_falls_back_to_first_option_on_llm_error(self, platform_with_llm):
        platform_with_llm._llm.invoke.side_effect = RuntimeError("LLM down")
        result = await platform_with_llm._answer_with_llm("Fav color?", ["Red", "Blue"])
        assert result == "Red"

    @pytest.mark.asyncio
    async def test_falls_back_to_yes_on_llm_error_no_options(self, platform_with_llm):
        platform_with_llm._llm.invoke.side_effect = RuntimeError("LLM down")
        result = await platform_with_llm._answer_with_llm("Tell me about yourself")
        assert result == "Yes"
