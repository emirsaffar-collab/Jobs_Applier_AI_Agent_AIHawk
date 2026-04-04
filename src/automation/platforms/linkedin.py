"""LinkedIn Easy Apply platform handler using Playwright.

Adapted from:
- NathanDuma/LinkedIn-Easy-Apply-Bot (Selenium → Playwright port)
- GodsScion/Auto_job_applier_linkedIn (AI form filling patterns)
- wodsuz/EasyApplyJobsBot (multi-step form handling)
"""
from __future__ import annotations

import asyncio
import re
import urllib.parse
from typing import Any

from playwright.async_api import Page, TimeoutError as PWTimeout

import config as cfg
from src.automation.platforms.base import BasePlatform, JobListing, ApplyResult
from src.logging import logger

_2FA_POLL_INTERVAL = 10  # seconds between countdown log messages
_2FA_MAX_RETRIES = 2     # total attempts before giving up

# LinkedIn selectors (as of 2025 — may need updates if LinkedIn changes DOM)
_SEL = {
    "email":           "#username",
    "password":        "#password",
    "login_btn":       "button[type='submit']",
    "feed":            ".feed-identity-module",
    "jobs_list":       ".jobs-search-results__list",
    "job_item":        ".jobs-search-results__list-item",
    "job_title":       ".job-card-list__title",
    "company_name":    ".job-card-container__company-name",
    "job_location":    ".job-card-container__metadata-item",
    "easy_apply_btn":  "button.jobs-apply-button",
    "modal":           ".jobs-easy-apply-modal",
    "next_btn":        "button[aria-label='Continue to next step']",
    "review_btn":      "button[aria-label='Review your application']",
    "submit_btn":      "button[aria-label='Submit application']",
    "close_modal":     "button[aria-label='Dismiss']",
    "already_applied": ".artdeco-inline-feedback--error",
    "follow_checkbox": "label[for='follow-company-checkbox']",
}

DATE_FILTER_MAP = {
    "24_hours": "r86400",
    "week":     "r604800",
    "month":    "r2592000",
    "all_time": "",
}

EXPERIENCE_LEVEL_MAP = {
    "internship":     "1",
    "entry":          "2",
    "associate":      "3",
    "mid_senior_level": "4",
    "director":       "5",
    "executive":      "6",
}

JOB_TYPE_MAP = {
    "full_time":  "F",
    "contract":   "C",
    "part_time":  "P",
    "temporary":  "T",
    "internship": "I",
    "other":      "O",
    "volunteer":  "V",
}


class LinkedInPlatform(BasePlatform):
    """LinkedIn Easy Apply automation."""

    LOGIN_URL = "https://www.linkedin.com/login"
    JOBS_BASE = "https://www.linkedin.com/jobs/search/"

    def __init__(self, llm=None):
        super().__init__(llm=llm)
        self.last_login_failure_reason: str = ""

    async def login(self, page: Page, credentials: dict, browser_manager=None) -> bool:
        self.last_login_failure_reason = ""
        email = credentials.get("email", "")
        password = credentials.get("password", "")
        if not email or not password:
            logger.warning("LinkedIn credentials missing.")
            return False

        # Check if already logged in via cookies (freshness check)
        if await self._cookies_are_fresh(page):
            logger.info("LinkedIn: already logged in via cookies.")
            return True

        # Navigate to login page
        await page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        await self._human_delay(1, 2)

        try:
            await page.fill(_SEL["email"], email)
            await self._human_delay(0.5, 1.5)
            await page.fill(_SEL["password"], password)
            await self._human_delay(0.5, 1.0)
            await page.click(_SEL["login_btn"])
            await self._human_delay(4, 7)
        except Exception as exc:
            logger.error("LinkedIn login form error: {}", exc)
            return False

        # Check for 2FA / security challenge
        if "/checkpoint/" in page.url or "/challenge/" in page.url:
            passed = await self._handle_2fa(page, browser_manager)
            if not passed:
                return False

        return await self._is_logged_in(page)

    async def _cookies_are_fresh(self, page: Page) -> bool:
        """Return True if existing cookies already grant LinkedIn feed access."""
        try:
            await page.goto("https://www.linkedin.com/feed", wait_until="domcontentloaded", timeout=20000)
            return await self._is_logged_in(page)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 2FA / security-challenge handling
    # ------------------------------------------------------------------

    async def _handle_2fa(self, page: Page, browser_manager=None) -> bool:
        """Wait for the user to complete a LinkedIn 2FA / security challenge.

        Returns True if the challenge was completed successfully.
        """
        is_headless = getattr(browser_manager, "headless", False) if browser_manager else False
        timeout = cfg.TWO_FA_TIMEOUT_SECONDS

        # --- TOTP auto-fill (works in headless mode) ---
        totp_secret = getattr(cfg, "TWO_FA_OTP_SECRET", "")
        if totp_secret:
            try:
                import pyotp
                totp = pyotp.TOTP(totp_secret)
                code = totp.now()
                # Try common OTP input selectors
                for sel in (
                    "input[name='pin']",
                    "input[id*='otp']",
                    "input[id*='verification']",
                    "input[autocomplete='one-time-code']",
                    "input[type='text']",
                ):
                    try:
                        field = await page.wait_for_selector(sel, timeout=3000, state="visible")
                        if field:
                            await field.fill(code)
                            await self._human_delay(0.5, 1.0)
                            await page.keyboard.press("Enter")
                            await self._human_delay(3, 5)
                            if await self._is_logged_in(page):
                                logger.info("LinkedIn 2FA completed via TOTP.")
                                return True
                            break
                    except PWTimeout:
                        continue
            except ImportError:
                logger.warning(
                    "TWO_FA_OTP_SECRET is set but 'pyotp' is not installed. "
                    "Install it with: pip install pyotp"
                )
            except Exception as exc:
                logger.warning("TOTP 2FA attempt failed: {}", exc)

        if is_headless:
            logger.error(
                "LinkedIn 2FA/security check detected, but the browser is "
                "running in HEADLESS mode — you cannot complete it without a "
                "visible browser window.\n"
                "  → Run the bot once with headless=false to complete 2FA.\n"
                "  → After that, cookies will be saved and headless mode will "
                "work for subsequent runs.\n"
                "  → Alternatively, set TWO_FA_OTP_SECRET env var for automatic TOTP."
            )
            self.last_login_failure_reason = "2fa_headless"
            return False

        logger.warning(
            "LinkedIn 2FA / security check detected.\n"
            "  → Please complete the verification in the browser window.\n"
            "  → You have {} seconds to finish. The bot will wait.",
            timeout,
        )

        for attempt in range(1, _2FA_MAX_RETRIES + 1):
            remaining = timeout
            while remaining > 0:
                try:
                    await page.wait_for_url(
                        "**/feed**", timeout=_2FA_POLL_INTERVAL * 1000
                    )
                    # Success — user completed the challenge
                    logger.info(
                        "2FA completed successfully. Cookies will be saved so "
                        "future logins should not require 2FA again."
                    )
                    return True
                except PWTimeout:
                    remaining -= _2FA_POLL_INTERVAL
                    if remaining > 0:
                        logger.info(
                            "2FA: waiting… {}s remaining. Complete the "
                            "verification in the browser window.",
                            remaining,
                        )

            # Timed out on this attempt
            if attempt < _2FA_MAX_RETRIES:
                logger.warning(
                    "2FA timed out (attempt {}/{}). Retrying wait…",
                    attempt, _2FA_MAX_RETRIES,
                )
            else:
                logger.error(
                    "Timed out waiting for LinkedIn 2FA after {} attempts "
                    "({}s each). Skipping LinkedIn for this run.\n"
                    "  Tip: If you keep seeing this, log into LinkedIn manually "
                    "in your normal browser first to mark your device as trusted.",
                    _2FA_MAX_RETRIES, timeout,
                )

        self.last_login_failure_reason = "2fa_timeout"
        return False

    async def search_jobs(self, page: Page, preferences: dict[str, Any]) -> list[JobListing]:
        """Search LinkedIn for jobs matching work_preferences.yaml content."""
        positions = preferences.get("positions", [])
        locations = preferences.get("locations", [])
        if not positions or not locations:
            logger.warning("No positions or locations configured.")
            return []

        jobs: list[JobListing] = []
        blacklisted_companies = {c.lower() for c in preferences.get("company_blacklist", [])}
        blacklisted_titles = {t.lower() for t in preferences.get("title_blacklist", [])}

        for position in positions:
            for location in locations:
                url = self._build_search_url(position, location, preferences)
                logger.info("LinkedIn search: {} in {}", position, location)
                page_jobs = await self._scrape_search_page(
                    page, url, blacklisted_companies, blacklisted_titles
                )
                jobs.extend(page_jobs)

        # De-duplicate by URL
        seen: set[str] = set()
        unique: list[JobListing] = []
        for j in jobs:
            if j.url not in seen:
                seen.add(j.url)
                unique.append(j)
        logger.info("LinkedIn: {} unique jobs found.", len(unique))
        return unique

    async def apply_to_job(
        self,
        page: Page,
        job: JobListing | dict,
        resume_path: str = "",
        cover_letter_path: str = "",
    ) -> ApplyResult:
        if isinstance(job, dict):
            url = job.get("url", "")
        else:
            url = job.url

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self._human_delay(2, 4)

            # Check if already applied
            if await self._already_applied(page):
                return ApplyResult(skipped=True, reason="already applied")

            # Click Easy Apply button
            try:
                btn = await page.wait_for_selector(
                    _SEL["easy_apply_btn"], timeout=8000, state="visible"
                )
            except PWTimeout:
                return ApplyResult(skipped=True, reason="no Easy Apply button")

            btn_text = (await btn.text_content() or "").strip()
            if "easy apply" not in btn_text.lower():
                return ApplyResult(skipped=True, reason="not an Easy Apply job")

            await btn.click()
            await self._human_delay(2, 3)

            # Handle multi-step modal
            result = await self._handle_application_modal(page, resume_path, cover_letter_path)
            return result

        except PWTimeout:
            return ApplyResult(reason="timeout navigating to job page")
        except Exception as exc:
            logger.error("LinkedIn apply error for {}: {}", url, exc)
            return ApplyResult(reason=str(exc))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _is_logged_in(self, page: Page) -> bool:
        try:
            await page.wait_for_selector(_SEL["feed"], timeout=5000)
            return True
        except PWTimeout:
            pass
        # Alternative: check URL
        return "feed" in page.url or "mynetwork" in page.url

    async def _already_applied(self, page: Page) -> bool:
        try:
            el = await page.query_selector(".jobs-s-apply__application-link")
            if el:
                text = (await el.text_content() or "").lower()
                return "applied" in text
        except Exception as exc:
            logger.debug("LinkedIn _already_applied check error: {}", exc)
        return False

    def _build_search_url(self, position: str, location: str, prefs: dict) -> str:
        params: dict[str, str] = {
            "keywords":  position,
            "location":  location,
            "f_LF":      "f_AL",   # Easy Apply only
            "origin":    "JOB_SEARCH_PAGE_JOB_FILTER",
        }

        # Date filter
        date = prefs.get("date", {})
        for key, value in DATE_FILTER_MAP.items():
            if date.get(key) and value:
                params["f_TPR"] = value
                break

        # Experience levels
        exp = prefs.get("experience_level", {})
        levels = [v for k, v in EXPERIENCE_LEVEL_MAP.items() if exp.get(k)]
        if levels:
            params["f_E"] = ",".join(levels)

        # Job types
        jt = prefs.get("job_types", {})
        types = [v for k, v in JOB_TYPE_MAP.items() if jt.get(k)]
        if types:
            params["f_JT"] = ",".join(types)

        # Remote
        remote = prefs.get("remote", False)
        hybrid = prefs.get("hybrid", False)
        onsite = prefs.get("onsite", False)
        work_types = []
        if remote:
            work_types.append("2")
        if hybrid:
            work_types.append("3")
        if onsite:
            work_types.append("1")
        if work_types:
            params["f_WT"] = ",".join(work_types)

        # Salary filter (LinkedIn f_SB2 buckets)
        salary = prefs.get("salary", {})
        sal_min = salary.get("min", 0) if isinstance(salary, dict) else 0
        if sal_min > 0:
            bucket = self._salary_bucket(sal_min)
            if bucket:
                params["f_SB2"] = bucket

        return self.JOBS_BASE + "?" + urllib.parse.urlencode(params)

    @staticmethod
    def _salary_bucket(min_salary: int) -> str | None:
        """Map a minimum annual salary to LinkedIn's f_SB2 bucket parameter."""
        # LinkedIn salary buckets (approximate annual USD thresholds)
        if min_salary >= 140000:
            return "6"
        if min_salary >= 120000:
            return "5"
        if min_salary >= 100000:
            return "4"
        if min_salary >= 80000:
            return "3"
        if min_salary >= 60000:
            return "2"
        if min_salary >= 40000:
            return "1"
        return None

    async def _scrape_search_page(
        self,
        page: Page,
        url: str,
        blacklisted_companies: set[str],
        blacklisted_titles: set[str],
        max_pages: int = 5,
    ) -> list[JobListing]:
        jobs: list[JobListing] = []
        current_url = url

        for page_num in range(max_pages):
            await page.goto(current_url, wait_until="domcontentloaded", timeout=30000)
            await self._human_delay(2, 4)

            # Scroll to load all job cards
            try:
                results_el = await page.query_selector(_SEL["jobs_list"])
                if results_el:
                    await results_el.scroll_into_view_if_needed()
                    for _ in range(3):
                        await page.keyboard.press("End")
                        await asyncio.sleep(0.8)
            except Exception as exc:
                logger.debug("LinkedIn scroll error: {}", exc)

            # Collect job tiles
            items = await page.query_selector_all(_SEL["job_item"])
            if not items:
                break

            for item in items:
                try:
                    title_el = await item.query_selector(_SEL["job_title"])
                    company_el = await item.query_selector(_SEL["company_name"])
                    location_el = await item.query_selector(_SEL["job_location"])

                    title = (await title_el.text_content() if title_el else "").strip()
                    company = (await company_el.text_content() if company_el else "").strip()
                    location = (await location_el.text_content() if location_el else "").strip()
                    link = (await title_el.get_attribute("href") or "") if title_el else ""
                    if link:
                        link = link.split("?")[0]  # strip tracking params

                    if not title or not link:
                        continue

                    # Blacklist checks
                    if company.lower() in blacklisted_companies:
                        continue
                    if any(w == title.lower() or w in title.lower().split() for w in blacklisted_titles):
                        continue

                    # Get description by clicking the job tile
                    description = await self._get_job_description(page, item)

                    jobs.append(JobListing(
                        title=title,
                        company=company,
                        location=location,
                        url=link,
                        description=description,
                        platform="linkedin",
                        apply_method="easy_apply",
                    ))
                except Exception as exc:
                    logger.debug("Error parsing job tile: {}", exc)
                    continue

            # Next page
            try:
                next_btn = await page.query_selector("button[aria-label='View next page']")
                if not next_btn:
                    break
                is_disabled = await next_btn.get_attribute("disabled")
                if is_disabled:
                    break
                await next_btn.click()
                await self._human_delay(2, 4)
                current_url = page.url
            except Exception:
                break

        return jobs

    async def _get_job_description(self, page: Page, item) -> str:
        """Click a job tile and return the description text."""
        try:
            await item.click()
            await self._human_delay(1, 2)
            desc_el = await page.query_selector(".jobs-description__content")
            if desc_el:
                return (await desc_el.text_content() or "").strip()
        except Exception as exc:
            logger.debug("LinkedIn get_job_description error: {}", exc)
        return ""

    async def _handle_application_modal(
        self, page: Page, resume_path: str, cover_letter_path: str
    ) -> ApplyResult:
        """Navigate through the Easy Apply multi-step modal and submit."""
        step = 0
        max_steps = 10

        while step < max_steps:
            await self._human_delay(1, 2)

            # Check if modal is open
            modal = await page.query_selector(_SEL["modal"])
            if not modal:
                # Modal closed — check for a confirmation indicator
                confirmed = await self._verify_submission(page)
                return ApplyResult(success=True, confirmed=confirmed)

            # Fill form fields on current step
            await self._fill_form_fields(page, resume_path, cover_letter_path)
            await self._human_delay(0.5, 1.5)

            # Uncheck "follow company" if present
            try:
                follow = await page.query_selector(_SEL["follow_checkbox"])
                if follow:
                    await follow.click()
            except Exception as exc:
                logger.debug("LinkedIn unfollow checkbox error: {}", exc)

            # Determine which button to click
            submit_btn = await page.query_selector(_SEL["submit_btn"])
            if submit_btn:
                await submit_btn.click()
                await self._human_delay(2, 4)
                confirmed = await self._verify_submission(page)
                return ApplyResult(success=True, confirmed=confirmed)

            review_btn = await page.query_selector(_SEL["review_btn"])
            if review_btn:
                await review_btn.click()
                step += 1
                continue

            next_btn = await page.query_selector(_SEL["next_btn"])
            if next_btn:
                await next_btn.click()
                step += 1
                continue

            # No button found — try clicking any visible primary button
            try:
                primaries = await page.query_selector_all(".artdeco-button--primary")
                for primary in primaries:
                    if await primary.is_visible():
                        await primary.click()
                        step += 1
                        break
                else:
                    primary = None
                if primary and await primary.is_visible():
                    continue
            except Exception as exc:
                logger.debug("LinkedIn primary button click error: {}", exc)

            # Stuck — close modal and skip
            try:
                close = await page.query_selector(_SEL["close_modal"])
                if close:
                    await close.click()
                    await self._human_delay(1, 2)
                    discard = await page.query_selector("button[data-control-name='discard_native_overlay']")
                    if discard:
                        await discard.click()
            except Exception as exc:
                logger.debug("LinkedIn close modal error: {}", exc)
            return ApplyResult(skipped=True, reason="stuck on step")

        return ApplyResult(skipped=True, reason="exceeded max steps")

    async def _verify_submission(self, page: Page) -> bool:
        """Check for post-submit confirmation indicators on the LinkedIn page.

        Returns True when a confirmation signal is detected, False otherwise.
        """
        try:
            # Wait briefly for the page to settle
            await asyncio.sleep(2)

            # 1. LinkedIn success feedback element
            feedback = await page.query_selector(".artdeco-inline-feedback--success")
            if feedback:
                return True

            # 2. "Your application was sent" toast / heading text
            for selector in (
                "text=Your application was sent",
                "text=Application submitted",
                "h3:has-text('submitted')",
            ):
                try:
                    el = await page.query_selector(selector)
                    if el and await el.is_visible():
                        return True
                except Exception:
                    pass

            # 3. URL redirect to recommended jobs (LinkedIn often redirects here)
            if "/jobs/collections/recommended" in page.url:
                return True

            # 4. Generic confirmation URL patterns
            url_lower = page.url.lower()
            if any(p in url_lower for p in ("/confirmation", "/thank-you", "/success", "/applied")):
                return True

        except Exception as exc:
            logger.debug("LinkedIn _verify_submission error: {}", exc)

        return False

    async def _fill_form_fields(
        self, page: Page, resume_path: str, cover_letter_path: str
    ) -> None:
        """Auto-fill all form inputs on the current modal step."""

        # Upload resume if a file input exists and we have a path
        if resume_path:
            try:
                file_inputs = await page.query_selector_all("input[type='file']")
                for fi in file_inputs:
                    label = await fi.get_attribute("aria-label") or ""
                    if "resume" in label.lower() or not label:
                        await fi.set_input_files(resume_path)
                        await self._human_delay(1, 2)
                        break
            except Exception as exc:
                logger.debug("Resume upload error: {}", exc)

        # Upload cover letter
        if cover_letter_path:
            try:
                file_inputs = await page.query_selector_all("input[type='file']")
                for fi in file_inputs:
                    label = await fi.get_attribute("aria-label") or ""
                    if "cover" in label.lower():
                        await fi.set_input_files(cover_letter_path)
                        await self._human_delay(1, 2)
                        break
            except Exception as exc:
                logger.debug("Cover letter upload error: {}", exc)

        # Fill text inputs / textareas
        try:
            inputs = await page.query_selector_all(
                ".jobs-easy-apply-form-section__form-input input[type='text'],"
                ".jobs-easy-apply-form-section__form-input input[type='number'],"
                ".jobs-easy-apply-form-section__form-input textarea"
            )
            for inp in inputs:
                value = (await inp.input_value()).strip()
                if value:
                    continue  # already filled
                # Try multiple strategies to find the label
                label_el = await inp.evaluate_handle(
                    """el => {
                        // Try closest label wrapper
                        const wrapper = el.closest('.jobs-easy-apply-form-element');
                        if (wrapper) {
                            const lbl = wrapper.querySelector('label');
                            if (lbl) return lbl;
                        }
                        // Try aria-label
                        const id = el.id;
                        if (id) {
                            const lbl = document.querySelector('label[for="' + id + '"]');
                            if (lbl) return lbl;
                        }
                        // Walk up to find nearest label
                        let parent = el.parentElement;
                        for (let i = 0; i < 5 && parent; i++) {
                            const lbl = parent.querySelector('label');
                            if (lbl) return lbl;
                            parent = parent.parentElement;
                        }
                        return null;
                    }"""
                )
                label_el = label_el.as_element() if label_el else None
                label_text = (await label_el.text_content() if label_el else "").strip()
                answer = await self._answer_with_llm(label_text or "Please fill in")
                tag = await inp.evaluate("el => el.tagName.toLowerCase()")
                await inp.fill(answer[:500])
                await self._human_delay(0.3, 0.8)
        except Exception as exc:
            logger.debug("Text input fill error: {}", exc)

        # Handle radio buttons / checkboxes
        try:
            fieldsets = await page.query_selector_all(
                ".jobs-easy-apply-form-section fieldset"
            )
            for fs in fieldsets:
                legend = await fs.query_selector("legend")
                question = (await legend.text_content() if legend else "").strip()
                radios = await fs.query_selector_all("input[type='radio']")
                if not radios:
                    continue
                options = []
                for r in radios:
                    # Get label via for= attribute or parent label element
                    r_id = await r.get_attribute("id")
                    lbl = None
                    if r_id:
                        lbl = await page.query_selector(f"label[for='{r_id}']")
                    if not lbl:
                        lbl = await r.evaluate_handle(
                            "el => el.closest('label') || el.parentElement.querySelector('label')"
                        )
                        lbl = lbl.as_element() if lbl else None
                    options.append((await lbl.text_content() if lbl else "").strip())
                best = await self._answer_with_llm(question, options)
                for i, r in enumerate(radios):
                    if options[i].lower() == best.lower():
                        await r.click()
                        break
                else:
                    await radios[0].click()  # default to first
                await self._human_delay(0.3, 0.8)
        except Exception as exc:
            logger.debug("Radio/checkbox fill error: {}", exc)

        # Handle dropdowns (select elements)
        try:
            selects = await page.query_selector_all(
                ".jobs-easy-apply-form-section select"
            )
            for sel in selects:
                value = await sel.input_value()
                if value and value != "Select an option":
                    continue
                options = await sel.query_selector_all("option")
                texts = [(await o.text_content() or "").strip() for o in options]
                # Find label for select element
                sel_id = await sel.get_attribute("id")
                label_el = None
                if sel_id:
                    label_el = await page.query_selector(f"label[for='{sel_id}']")
                if not label_el:
                    label_el_handle = await sel.evaluate_handle(
                        """el => {
                            let parent = el.parentElement;
                            for (let i = 0; i < 5 && parent; i++) {
                                const lbl = parent.querySelector('label');
                                if (lbl) return lbl;
                                parent = parent.parentElement;
                            }
                            return null;
                        }"""
                    )
                    label_el = label_el_handle.as_element() if label_el_handle else None
                question = (await label_el.text_content() if label_el else "").strip()
                best = await self._answer_with_llm(question, [t for t in texts if t])
                await sel.select_option(label=best)
                await self._human_delay(0.3, 0.8)
        except Exception as exc:
            logger.debug("Dropdown fill error: {}", exc)
