"""Abstract base class for all job platform handlers."""
from __future__ import annotations

import random
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Page, TimeoutError as PWTimeout

from src.logging import logger


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
    confirmed: bool = False  # True when post-submit confirmation was verified


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
            except PWTimeout:
                if attempt < retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                logger.debug("_safe_click timed out for selector '{}' after {} retries", selector, retries)
                return False
            except Exception as exc:
                logger.debug("_safe_click error for selector '{}': {}", selector, exc)
                return False

    async def _safe_fill(self, page: Page, selector: str, value: str, *, timeout: int = 5000, retries: int = 2) -> bool:
        """Fill a form field with retry. Returns True on success."""
        for attempt in range(retries + 1):
            try:
                await page.fill(selector, value, timeout=timeout)
                return True
            except PWTimeout:
                if attempt < retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                logger.debug("_safe_fill timed out for selector '{}' after {} retries", selector, retries)
                return False
            except Exception as exc:
                logger.debug("_safe_fill error for selector '{}': {}", selector, exc)
                return False

    async def _check_and_solve_captcha(self, page: Page) -> bool:
        """Detect and solve CAPTCHAs on the current page. Returns True if solved."""
        try:
            from src.utils.captcha_solver import create_captcha_solver, detect_and_solve_captcha
            import config as cfg
            # Determine which API key to use for the configured provider
            provider = getattr(cfg, "CAPTCHA_PROVIDER", "capsolver")
            if provider == "2captcha":
                api_key = getattr(cfg, "TWOCAPTCHA_API_KEY", "") or cfg.CAPSOLVER_API_KEY
            elif provider == "anticaptcha":
                api_key = getattr(cfg, "ANTICAPTCHA_API_KEY", "") or cfg.CAPSOLVER_API_KEY
            else:
                api_key = cfg.CAPSOLVER_API_KEY
            if api_key:
                solver = create_captcha_solver(provider, api_key)
                return await detect_and_solve_captcha(page, solver)
        except ImportError:
            logger.debug("CAPTCHA solver not available")
        except Exception as exc:
            logger.warning("CAPTCHA solving failed: {}", exc)
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
        except (PWTimeout, OSError) as exc:
            logger.debug("Failed to fill text field '{}': {}", selector, exc)
            await page.fill(selector, "Yes")
        except Exception as exc:
            logger.warning("LLM answer_text_field error for '{}': {}", question[:80], exc)
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
        except Exception as exc:
            logger.warning("LLM answer_with_llm error for '{}': {}", question[:80], exc)
            return options[0] if options else "Yes"

    @staticmethod
    def _salary_matches(description: str, salary_prefs: dict) -> bool:
        """Check whether a job description satisfies the configured salary filter.

        Returns True when:
        - No salary filter is configured (min == 0).
        - A salary figure is found in the description that meets the minimum.
        - No salary figure can be extracted from the description (benefit of the doubt).
        """
        import re as _re
        sal_min = salary_prefs.get("min", 0) if isinstance(salary_prefs, dict) else 0
        if not sal_min:
            return True  # no filter

        # Extract salary-like numbers from the description
        # Matches patterns like $80k, $80,000, $80K, 80K, 80,000
        raw_numbers: list[int] = []
        for match in _re.finditer(
            r"\$?\s*(\d{1,3}(?:,\d{3})*|\d+)\s*[kK]?\b", description or ""
        ):
            num_str = match.group(1).replace(",", "")
            try:
                num = int(num_str)
            except ValueError:
                continue
            # Determine if 'k' suffix present
            full = match.group(0)
            if "k" in full.lower():
                num *= 1000
            # Only treat numbers in a plausible salary range (20K–2M)
            if 20_000 <= num <= 2_000_000:
                raw_numbers.append(num)

        if not raw_numbers:
            # Cannot determine salary — do not filter out
            return True

        return max(raw_numbers) >= sal_min
