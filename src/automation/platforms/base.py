"""Abstract base class for all job platform handlers."""
from __future__ import annotations

import random
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Page


@dataclass
class JobListing:
    """A single job discovered on a platform."""
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    platform: str = ""
    job_id: str = ""
    apply_method: str = ""      # "easy_apply", "external", "quick_apply", etc.
    extra: dict = field(default_factory=dict)


@dataclass
class ApplyResult:
    """Outcome of a single application attempt."""
    success: bool = False
    skipped: bool = False
    reason: str = ""


class BasePlatform(ABC):
    """All platform handlers implement this interface."""

    def __init__(self, llm=None):
        self._llm = llm  # AIModel from llm_manager — may be None

    @abstractmethod
    async def login(
        self,
        page: Page,
        credentials: dict[str, str],
        browser_manager=None,
    ) -> bool:
        """Log in to the platform. Return True on success."""
        ...

    @abstractmethod
    async def search_jobs(
        self,
        page: Page,
        preferences: dict[str, Any],
    ) -> list[JobListing]:
        """Search for jobs matching preferences. Return a list of JobListings."""
        ...

    @abstractmethod
    async def apply_to_job(
        self,
        page: Page,
        job: JobListing | dict,
        resume_path: str = "",
        cover_letter_path: str = "",
    ) -> ApplyResult:
        """Apply to a single job. Return an ApplyResult."""
        ...

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _human_delay(self, lo: float = 1.0, hi: float = 3.0) -> None:
        """Wait a random amount to appear more human."""
        await asyncio.sleep(random.uniform(lo, hi))

    async def _safe_click(self, page: Page, selector: str, *, timeout: int = 5000, retries: int = 2) -> bool:
        """Click an element with retry on transient failures. Returns True on success."""
        for attempt in range(retries + 1):
            try:
                await page.click(selector, timeout=timeout)
                return True
            except Exception:
                if attempt < retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                return False

    async def _safe_fill(self, page: Page, selector: str, value: str, *, timeout: int = 5000, retries: int = 2) -> bool:
        """Fill a form field with retry. Returns True on success."""
        for attempt in range(retries + 1):
            try:
                await page.fill(selector, value, timeout=timeout)
                return True
            except Exception:
                if attempt < retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                return False

    async def _check_and_solve_captcha(self, page: Page) -> bool:
        """Detect and solve CAPTCHAs on the current page. Returns True if solved."""
        try:
            from src.utils.captcha_solver import CaptchaSolver, detect_and_solve_captcha
            import config as cfg
            if cfg.CAPSOLVER_API_KEY:
                solver = CaptchaSolver(api_key=cfg.CAPSOLVER_API_KEY)
                return await detect_and_solve_captcha(page, solver)
        except Exception:
            pass
        return False

    async def _answer_text_field(self, page: Page, selector: str, question: str) -> None:
        """Use LLM to answer a free-text application question."""
        if self._llm is None:
            return
        try:
            answer = self._llm.invoke(
                f"Answer this job application question concisely (1-3 sentences): {question}"
            )
            if hasattr(answer, "content"):
                answer = answer.content
            await page.fill(selector, str(answer).strip())
        except Exception:
            await page.fill(selector, "Yes")

    async def _answer_with_llm(self, question: str, options: list[str] | None = None) -> str:
        """Ask the LLM for the best answer given question + optional options."""
        if self._llm is None:
            return options[0] if options else "Yes"
        prompt = f"Job application question: {question}"
        if options:
            prompt += f"\nOptions: {', '.join(options)}"
            prompt += "\nRespond with ONLY the best option text, nothing else."
        else:
            prompt += "\nAnswer concisely (1-2 sentences)."
        try:
            result = self._llm.invoke(prompt)
            if hasattr(result, "content"):
                result = result.content
            return str(result).strip()
        except Exception:
            return options[0] if options else "Yes"
