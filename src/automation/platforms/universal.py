"""Universal AI-driven job application handler.

Applies to any career page URL using LLM-guided form filling.
Includes targeted strategies for common ATS platforms (Greenhouse, Lever,
Workday, SmartRecruiters) with a generic fallback.
"""
from __future__ import annotations

import re
from typing import Any

from playwright.async_api import Page, TimeoutError as PWTimeout

from src.automation.platforms.base import BasePlatform, JobListing, ApplyResult
from src.logging import logger

# Regex to detect confirmation text on any post-submit page
_CONFIRM_RE = re.compile(
    r"application.*submitted|thank\s+you.*applying|we.*received.*application"
    r"|your.*application.*sent|application.*received",
    re.IGNORECASE,
)


def _detect_ats(url: str) -> str:
    """Inspect a job URL and return a short ATS identifier string."""
    url_lower = url.lower()
    if "greenhouse.io" in url_lower or "boards.greenhouse.io" in url_lower:
        return "greenhouse"
    if "jobs.lever.co" in url_lower or "lever.co" in url_lower:
        return "lever"
    if "myworkdayjobs.com" in url_lower or "workday.com" in url_lower:
        return "workday"
    if "smartrecruiters.com" in url_lower:
        return "smartrecruiters"
    if "icims.com" in url_lower:
        return "icims"
    return "generic"


async def _check_confirmation(page: Page) -> bool:
    """Return True when a post-submit confirmation indicator is found."""
    try:
        url_lower = page.url.lower()
        if any(p in url_lower for p in ("/confirmation", "/thank-you", "/success", "/applied", "/submitted")):
            return True
        body = (await page.text_content("body") or "").strip()
        if _CONFIRM_RE.search(body):
            return True
    except Exception:
        pass
    return False


class UniversalPlatform(BasePlatform):
    """Apply to any job page via AI-driven form detection and filling.

    This platform doesn't do its own job search — it processes a list of
    job URLs provided directly in preferences["universal_urls"].
    """

    async def login(self, page: Page, credentials: dict, browser_manager=None) -> bool:
        # Universal platform handles no platform-wide login
        return True

    async def search_jobs(self, page: Page, preferences: dict[str, Any]) -> list[JobListing]:
        """Return jobs from manually-specified URLs in preferences."""
        urls = preferences.get("universal_urls", [])
        jobs: list[JobListing] = []
        for url in urls:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self._human_delay(1, 2)
            title = await page.title()
            jobs.append(JobListing(
                title=title,
                company="",
                location="",
                url=url,
                platform="universal",
                apply_method="ai_form_fill",
            ))
        return jobs

    async def apply_to_job(
        self,
        page: Page,
        job: JobListing | dict,
        resume_path: str = "",
        cover_letter_path: str = "",
    ) -> ApplyResult:
        url = job.get("url", "") if isinstance(job, dict) else job.url
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self._human_delay(2, 3)

            ats = _detect_ats(url)
            logger.debug("Universal ATS detected: {} for {}", ats, url)

            if ats == "greenhouse":
                return await self._apply_greenhouse(page, resume_path, cover_letter_path)
            if ats == "lever":
                return await self._apply_lever(page, resume_path, cover_letter_path)
            if ats == "workday":
                return await self._apply_workday(page, resume_path, cover_letter_path)
            if ats == "smartrecruiters":
                return await self._apply_smartrecruiters(page, resume_path, cover_letter_path)
            # Generic / iCIMS fallback
            return await self._apply_generic(page, resume_path, cover_letter_path)

        except PWTimeout:
            return ApplyResult(reason="timeout")
        except Exception as exc:
            logger.error("Universal apply error for {}: {}", url, exc)
            return ApplyResult(reason=str(exc))

    # ------------------------------------------------------------------
    # ATS-specific strategies
    # ------------------------------------------------------------------

    async def _apply_greenhouse(
        self, page: Page, resume_path: str, cover_letter_path: str
    ) -> ApplyResult:
        """Greenhouse ATS strategy."""
        # Click the apply button
        for btn_sel in (
            "a:has-text('Apply for this Job')",
            "a:has-text('Apply')",
            "button:has-text('Apply')",
        ):
            btn = await page.query_selector(btn_sel)
            if btn:
                await btn.click()
                await self._human_delay(2, 3)
                break

        await self._fill_all_inputs(page, resume_path, cover_letter_path)
        await self._human_delay(1, 2)

        submit = await page.query_selector("input[type='submit'], button[type='submit']")
        if submit:
            await submit.click()
            await self._human_delay(3, 5)
            confirmed = await _check_confirmation(page)
            return ApplyResult(success=True, confirmed=confirmed)

        return ApplyResult(skipped=True, reason="greenhouse: submit button not found")

    async def _apply_lever(
        self, page: Page, resume_path: str, cover_letter_path: str
    ) -> ApplyResult:
        """Lever ATS strategy."""
        for btn_sel in (
            "a:has-text('Apply for this position')",
            "a:has-text('Apply')",
            "button:has-text('Apply')",
        ):
            btn = await page.query_selector(btn_sel)
            if btn:
                await btn.click()
                await self._human_delay(2, 3)
                break

        await self._fill_all_inputs(page, resume_path, cover_letter_path)
        await self._human_delay(1, 2)

        submit = await page.query_selector(
            "button[type='submit'], input[type='submit'], button:has-text('Submit Application')"
        )
        if submit:
            await submit.click()
            await self._human_delay(3, 5)
            confirmed = await _check_confirmation(page)
            return ApplyResult(success=True, confirmed=confirmed)

        return ApplyResult(skipped=True, reason="lever: submit button not found")

    async def _apply_workday(
        self, page: Page, resume_path: str, cover_letter_path: str
    ) -> ApplyResult:
        """Workday ATS strategy — handles multi-step wizard."""
        # Click Apply
        for btn_sel in (
            "a:has-text('Apply')",
            "button:has-text('Apply')",
            "[data-automation-id='applyButton']",
        ):
            btn = await page.query_selector(btn_sel)
            if btn:
                await btn.click()
                await self._human_delay(3, 5)
                break

        max_steps = 15
        for _ in range(max_steps):
            await self._fill_all_inputs(page, resume_path, cover_letter_path)
            await self._human_delay(1, 2)

            # Check for submit
            submit = await page.query_selector(
                "[data-automation-id='bottom-navigation-next-button']:has-text('Submit')"
                ", button:has-text('Submit')"
            )
            if submit:
                await submit.click()
                await self._human_delay(4, 6)
                confirmed = await _check_confirmation(page)
                return ApplyResult(success=True, confirmed=confirmed)

            # Advance to next step
            next_btn = await page.query_selector(
                "[data-automation-id='bottom-navigation-next-button']"
                ", button:has-text('Next')"
                ", button:has-text('Save and Continue')"
            )
            if next_btn:
                await next_btn.click()
                await self._human_delay(2, 3)
                continue

            # No progress possible
            break

        return ApplyResult(skipped=True, reason="workday: could not complete wizard")

    async def _apply_smartrecruiters(
        self, page: Page, resume_path: str, cover_letter_path: str
    ) -> ApplyResult:
        """SmartRecruiters ATS strategy."""
        for btn_sel in (
            "button:has-text('Apply')",
            "a:has-text('Apply')",
            "[class*='apply-button']",
        ):
            btn = await page.query_selector(btn_sel)
            if btn:
                await btn.click()
                await self._human_delay(2, 3)
                break

        await self._fill_all_inputs(page, resume_path, cover_letter_path)
        await self._human_delay(1, 2)

        submit = await page.query_selector(
            "button[type='submit']:has-text('Send'), "
            "button:has-text('Submit Application'), "
            "button[type='submit']"
        )
        if submit:
            await submit.click()
            await self._human_delay(3, 5)
            confirmed = await _check_confirmation(page)
            return ApplyResult(success=True, confirmed=confirmed)

        return ApplyResult(skipped=True, reason="smartrecruiters: submit button not found")

    async def _apply_generic(
        self, page: Page, resume_path: str, cover_letter_path: str
    ) -> ApplyResult:
        """Generic AI-driven strategy (original behaviour)."""
        # Find and click an "Apply" button
        apply_btn = await page.query_selector(
            "button:has-text('Apply'), a:has-text('Apply Now'), "
            "button:has-text('Apply Now'), a:has-text('Apply')"
        )
        if apply_btn:
            await apply_btn.click()
            await self._human_delay(2, 3)

        for _step in range(10):
            await self._human_delay(1, 2)
            filled = await self._fill_all_inputs(page, resume_path, cover_letter_path)

            submit = await page.query_selector(
                "button[type='submit']:has-text('Submit'), "
                "button:has-text('Submit Application'), "
                "input[type='submit']"
            )
            if submit:
                await submit.click()
                await self._human_delay(2, 4)
                confirmed = await _check_confirmation(page)
                return ApplyResult(success=True, confirmed=confirmed)

            next_btn = await page.query_selector(
                "button:has-text('Next'), button:has-text('Continue'), "
                "button[type='submit']:not(:has-text('Submit'))"
            )
            if next_btn:
                await next_btn.click()
                continue

            if not filled:
                break

        return ApplyResult(skipped=True, reason="could not determine form flow")

    # ------------------------------------------------------------------
    # Form filling helpers (unchanged from original)
    # ------------------------------------------------------------------

    async def _fill_all_inputs(
        self, page: Page, resume_path: str, cover_letter_path: str
    ) -> bool:
        """Fill all visible, unfilled inputs. Returns True if anything was filled."""
        filled_any = False

        # File inputs
        if resume_path:
            try:
                for fi in await page.query_selector_all("input[type='file']"):
                    label = (await fi.get_attribute("aria-label") or "").lower()
                    if not label or "resume" in label or "cv" in label:
                        await fi.set_input_files(resume_path)
                        await self._human_delay(0.5, 1.0)
                        filled_any = True
                        break
            except Exception as exc:
                logger.debug("Universal resume upload error: {}", exc)

        # Text inputs
        try:
            for inp in await page.query_selector_all(
                "input[type='text']:visible, input[type='email']:visible, "
                "input[type='tel']:visible, input[type='number']:visible, textarea:visible"
            ):
                value = (await inp.input_value()).strip()
                if value:
                    continue
                label_text = await self._get_label_text(page, inp)
                answer = await self._answer_with_llm(label_text or "Fill this field")
                await inp.fill(answer[:300])
                await self._human_delay(0.2, 0.5)
                filled_any = True
        except Exception as exc:
            logger.debug("Universal text fill error: {}", exc)

        # Select dropdowns
        try:
            for sel in await page.query_selector_all("select:visible"):
                value = await sel.input_value()
                if value:
                    continue
                options = [
                    (await o.text_content() or "").strip()
                    for o in await sel.query_selector_all("option")
                ]
                label_text = await self._get_label_text(page, sel)
                best = await self._answer_with_llm(label_text or "Select", [o for o in options if o])
                try:
                    await sel.select_option(label=best)
                    filled_any = True
                except Exception as exc:
                    logger.debug("Universal select_option error: {}", exc)
        except Exception as exc:
            logger.debug("Universal select fill error: {}", exc)

        return filled_any

    @staticmethod
    async def _get_label_text(page: Page, element) -> str:
        """Try to find the label text for an input element."""
        try:
            el_id = await element.get_attribute("id")
            if el_id:
                label = await page.query_selector(f"label[for='{el_id}']")
                if label:
                    return (await label.text_content() or "").strip()
            aria = await element.get_attribute("aria-label")
            if aria:
                return aria.strip()
            placeholder = await element.get_attribute("placeholder")
            if placeholder:
                return placeholder.strip()
        except PWTimeout:
            logger.debug("Timeout getting label text for element")
        except Exception as exc:
            logger.debug("Error getting label text: {}", exc)
        return ""
