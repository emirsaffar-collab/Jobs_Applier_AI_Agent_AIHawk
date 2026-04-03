"""Global bot manager: lifecycle (start/stop/pause) and main automation loop."""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from src.logging import logger

CREDENTIALS_PATH = Path("data_folder/credentials.yaml")
RESUME_PATH = Path("data_folder/plain_text_resume.yaml")


@dataclass
class BotConfig:
    """Configuration snapshot passed to a single bot run."""
    platforms: list[str]                # e.g. ["linkedin", "indeed"]
    credentials: dict[str, dict]        # {platform: {email, password, ...}}
    preferences: dict[str, Any]         # work_preferences.yaml content
    llm_api_key: str
    llm_model_type: str = "claude"
    llm_model: str = "claude-sonnet-4-6"
    min_score: int = 7
    max_applications: int = 50
    headless: bool = True
    generate_tailored_resume: bool = False
    # CAPTCHA solving
    capsolver_api_key: str = ""
    # Proxy rotation
    proxies: list[str] = field(default_factory=list)
    # Recruiter outreach
    recruiter_outreach_enabled: bool = False
    recruiter_outreach_daily_limit: int = 20
    recruiter_outreach_style: str = "professional"
    # Per-platform rate limits
    rate_limits: dict[str, int] = field(default_factory=dict)
    rate_limit_default: int = 80
    rate_limit_cooldown_minutes: float = 5.0


class BotManager:
    """Singleton that controls the automation bot lifecycle.

    The UI talks to this object via the FastAPI endpoints.
    Internally it runs a single asyncio Task that drives all platforms.
    """

    _instance: "BotManager | None" = None

    def __new__(cls) -> "BotManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self.status: str = "idle"        # idle | running | paused | stopping
        self.session_id: str = ""
        self._task: asyncio.Task | None = None
        self._pause_event: asyncio.Event = asyncio.Event()
        self._stop_event: asyncio.Event = asyncio.Event()
        self._pause_event.set()          # not paused by default
        self.stats: dict[str, Any] = {
            "applied": 0,
            "skipped": 0,
            "failed": 0,
            "current_platform": "",
            "current_job": "",
            "log": [],
        }
        self._progress_callbacks: list[Callable] = []

    # ------------------------------------------------------------------
    # Public control API
    # ------------------------------------------------------------------

    async def start(self, config: BotConfig) -> str:
        """Start the bot. Returns session_id. Raises if already running."""
        if self.status == "running":
            raise RuntimeError("Bot is already running.")
        self.session_id = str(uuid.uuid4())[:8]
        self._reset_stats()
        self._stop_event.clear()
        self._pause_event.set()
        self.status = "running"
        self._task = asyncio.create_task(self._run_loop(config))
        self._log(f"Bot started — session {self.session_id}")
        return self.session_id

    async def stop(self) -> None:
        self._stop_event.set()
        self._pause_event.set()  # unblock if paused
        self.status = "stopping"
        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=15)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        self.status = "idle"
        self._log("Bot stopped.")

    async def pause(self) -> None:
        if self.status == "running":
            self._pause_event.clear()
            self.status = "paused"
            self._log("Bot paused.")

    async def resume(self) -> None:
        if self.status == "paused":
            self._pause_event.set()
            self.status = "running"
            self._log("Bot resumed.")

    def get_status(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "session_id": self.session_id,
            "stats": dict(self.stats),
        }

    def register_progress_callback(self, cb: Callable) -> None:
        """Register an async callable that receives log messages."""
        self._progress_callbacks.append(cb)

    def unregister_progress_callback(self, cb: Callable) -> None:
        self._progress_callbacks = [c for c in self._progress_callbacks if c != cb]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reset_stats(self) -> None:
        self.stats = {
            "applied": 0,
            "skipped": 0,
            "failed": 0,
            "current_platform": "",
            "current_job": "",
            "log": [],
        }

    def _log(self, message: str) -> None:
        logger.info("[BotManager] {}", message)
        entry = {"msg": message}
        self.stats["log"].append(entry)
        # Keep last 500 log lines in memory
        if len(self.stats["log"]) > 500:
            self.stats["log"] = self.stats["log"][-500:]
        # Fire callbacks (non-blocking)
        for cb in list(self._progress_callbacks):
            try:
                asyncio.create_task(cb(entry))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Main automation loop
    # ------------------------------------------------------------------

    async def _run_loop(self, config: BotConfig) -> None:
        """Drive all configured platforms sequentially."""
        from src.automation.browser import BrowserManager
        from src.automation.application_tracker import ApplicationTracker
        from src.automation.job_ranker import JobRanker
        from src.automation.rate_limiter import RateLimiter
        from src.automation.recruiter_outreach import RecruiterOutreach
        from src.automation.platforms import get_platform
        from src.utils.captcha_solver import CaptchaSolver

        browser = BrowserManager(headless=config.headless, proxies=config.proxies)
        tracker = ApplicationTracker()
        captcha_solver = CaptchaSolver(api_key=config.capsolver_api_key)
        rate_limiter = RateLimiter(
            limits=config.rate_limits,
            default_limit=config.rate_limit_default,
            cooldown_minutes=config.rate_limit_cooldown_minutes,
        )

        # Build LLM model for ranking
        try:
            llm = self._build_llm(config)
        except Exception as exc:
            self._log(f"Failed to initialize LLM: {exc}")
            self.status = "idle"
            return

        # Load resume text
        resume_text = self._load_resume()
        ranker = JobRanker(llm, resume_text)

        # Recruiter outreach
        outreach: RecruiterOutreach | None = None
        if config.recruiter_outreach_enabled:
            outreach = RecruiterOutreach(
                llm=llm,
                daily_limit=config.recruiter_outreach_daily_limit,
                message_style=config.recruiter_outreach_style,
            )
            self._log("Recruiter outreach enabled (limit={}/day, style={})".format(
                config.recruiter_outreach_daily_limit, config.recruiter_outreach_style
            ))

        if captcha_solver.enabled:
            self._log("CAPTCHA solving enabled (CAPSolver).")
        if config.proxies:
            self._log(f"Proxy rotation enabled ({len(config.proxies)} proxies).")
        self._log(f"Rate limiting: {rate_limiter.get_limit('default')}/day default, "
                   f"{config.rate_limit_cooldown_minutes}min cooldown.")

        total_applied = 0

        try:
            await browser.launch()

            for platform_name in config.platforms:
                if self._stop_event.is_set():
                    break
                if total_applied >= config.max_applications:
                    self._log(f"Reached max_applications limit ({config.max_applications}).")
                    break

                # Check per-platform rate limit
                if not rate_limiter.can_apply(platform_name):
                    remaining = rate_limiter.remaining(platform_name)
                    self._log(f"Rate limit reached for {platform_name} ({remaining} remaining). Skipping.")
                    continue

                self.stats["current_platform"] = platform_name
                self._log(f"=== Platform: {platform_name} ===")

                platform_cls = get_platform(platform_name)
                if platform_cls is None:
                    self._log(f"Platform '{platform_name}' not implemented yet, skipping.")
                    continue

                platform = platform_cls(llm=llm)
                creds = config.credentials.get(platform_name, {})

                # Login
                page = await browser.new_page()
                try:
                    await browser.load_cookies(platform_name)
                    logged_in = await platform.login(page, creds, browser)
                    if not logged_in:
                        self._log(f"Login failed for {platform_name}, skipping.")
                        await page.close()
                        continue
                    await browser.save_cookies(platform_name)
                except Exception as exc:
                    self._log(f"Login error on {platform_name}: {exc}")
                    await page.close()
                    continue

                # Search jobs
                try:
                    jobs = await platform.search_jobs(page, config.preferences)
                    self._log(f"Found {len(jobs)} jobs on {platform_name}.")
                except Exception as exc:
                    self._log(f"Job search error on {platform_name}: {exc}")
                    await page.close()
                    continue

                # Process each job
                for job in jobs:
                    if self._stop_event.is_set():
                        break
                    if total_applied >= config.max_applications:
                        break

                    # Respect pause
                    await self._pause_event.wait()

                    company = job.company if hasattr(job, "company") else job.get("company", "")
                    title = job.title if hasattr(job, "title") else job.get("title", "")
                    url = job.url if hasattr(job, "url") else job.get("url", "")
                    description = job.description if hasattr(job, "description") else job.get("description", "")
                    self.stats["current_job"] = f"{title} @ {company}"

                    # Skip already seen URLs
                    if tracker.url_seen(url):
                        continue

                    # Record discovery
                    tracker.record_discovered(
                        platform=platform_name,
                        company=company,
                        title=title,
                        url=url,
                        session_id=self.session_id,
                    )

                    # Skip already applied company+title combos
                    if tracker.already_applied(company, title):
                        tracker.mark_skipped(url, "already applied")
                        self.stats["skipped"] += 1
                        self._log(f"Skip (already applied): {title} @ {company}")
                        continue

                    # Score the job
                    if description:
                        score_result = ranker.score(title, company, description)
                        score = score_result["score"]
                        tracker.update_score(url, score, score_result.get("reason", ""))
                        if score < config.min_score:
                            tracker.mark_skipped(url, f"score {score} < {config.min_score}")
                            self.stats["skipped"] += 1
                            self._log(f"Skip (score {score}): {title} @ {company}")
                            continue
                        self._log(f"Score {score}/10: {title} @ {company}")
                    else:
                        self._log(f"No description available, applying anyway: {title} @ {company}")

                    # Optionally generate tailored resume
                    resume_path = ""
                    cover_path = ""
                    if config.generate_tailored_resume and description:
                        try:
                            resume_path, cover_path = await asyncio.to_thread(
                                self._generate_docs, config, job
                            )
                            self._log(f"Generated tailored resume: {resume_path}")
                        except Exception as exc:
                            self._log(f"Resume generation failed: {exc}")

                    # Check per-platform rate limit before each application
                    if not rate_limiter.can_apply(platform_name):
                        self._log(f"Rate limit reached for {platform_name}, stopping platform.")
                        break

                    # Cooldown between applications
                    await rate_limiter.wait_cooldown(platform_name)

                    # Apply
                    try:
                        result = await platform.apply_to_job(
                            page, job, resume_path=resume_path, cover_letter_path=cover_path
                        )
                        result_success = result.success if hasattr(result, "success") else result.get("success")
                        result_skipped = result.skipped if hasattr(result, "skipped") else result.get("skipped")
                        result_reason = result.reason if hasattr(result, "reason") else result.get("reason", "")

                        if result_success:
                            tracker.mark_applied(url, resume_path, cover_path)
                            rate_limiter.record_application(platform_name)
                            self.stats["applied"] += 1
                            total_applied += 1
                            self._log(f"Applied: {title} @ {company}")

                            # Recruiter outreach (LinkedIn only, after successful apply)
                            recruiter_link = getattr(job, "extra", {}).get("recruiter_link", "") if hasattr(job, "extra") else (job.get("recruiter_link", "") if isinstance(job, dict) else "")
                            if outreach and recruiter_link and platform_name == "linkedin":
                                try:
                                    await outreach.send_referral_message(
                                        page,
                                        recruiter_url=recruiter_link,
                                        job_title=title,
                                        company=company,
                                    )
                                except Exception as out_exc:
                                    self._log(f"Outreach error: {out_exc}")

                        elif result_skipped:
                            tracker.mark_skipped(url, result_reason or "skipped")
                            self.stats["skipped"] += 1
                            self._log(f"Skipped: {title} — {result_reason}")
                        else:
                            tracker.mark_failed(url, result_reason or "unknown")
                            self.stats["failed"] += 1
                            self._log(f"Failed: {title} — {result_reason}")

                            # Check if failure might be CAPTCHA-related
                            reason = (result_reason or "").lower()
                            if captcha_solver.enabled and ("captcha" in reason or "verify" in reason):
                                from src.utils.captcha_solver import detect_and_solve_captcha
                                solved = await detect_and_solve_captcha(page, captcha_solver)
                                if solved:
                                    self._log("CAPTCHA solved — retrying application.")

                    except Exception as exc:
                        tracker.mark_failed(url, str(exc))
                        self.stats["failed"] += 1
                        self._log(f"Error applying to {title}: {exc}")

                await page.close()

        except Exception as exc:
            self._log(f"Bot crashed: {exc}")
            logger.exception("Bot loop crashed")
        finally:
            await captcha_solver.close()
            await browser.close()
            self.status = "idle"
            self.stats["current_platform"] = ""
            self.stats["current_job"] = ""

            # Log rate limiter stats
            rl_stats = rate_limiter.get_stats()
            if rl_stats:
                for plat, info in rl_stats.items():
                    self._log(f"  {plat}: {info['applied_24h']}/{info['limit']} applications (24h)")

            # Log outreach stats
            if outreach:
                self._log(
                    f"Outreach: sent={outreach.stats.sent}, "
                    f"skipped={outreach.stats.skipped}, failed={outreach.stats.failed}"
                )

            self._log(
                f"Bot finished. Applied: {self.stats['applied']}, "
                f"Skipped: {self.stats['skipped']}, Failed: {self.stats['failed']}"
            )

    # ------------------------------------------------------------------
    # Helpers for LLM and resume generation
    # ------------------------------------------------------------------

    @staticmethod
    def _build_llm(config: BotConfig):
        """Build an AIModel instance from the bot config.

        Sets the global config temporarily for AIAdapter, which reads
        cfg.LLM_MODEL_TYPE / cfg.LLM_MODEL during initialization.
        """
        import config as cfg
        # Store originals to restore after initialization
        orig_type, orig_model = cfg.LLM_MODEL_TYPE, cfg.LLM_MODEL
        try:
            cfg.LLM_MODEL_TYPE = config.llm_model_type
            cfg.LLM_MODEL = config.llm_model
            from src.libs.llm_manager import AIAdapter
            return AIAdapter(config={}, api_key=config.llm_api_key)
        finally:
            cfg.LLM_MODEL_TYPE = orig_type
            cfg.LLM_MODEL = orig_model

    @staticmethod
    def _load_resume() -> str:
        if RESUME_PATH.exists():
            return RESUME_PATH.read_text(encoding="utf-8")
        return ""

    @staticmethod
    def _generate_docs(config: BotConfig, job: dict) -> tuple[str, str]:
        """Generate tailored resume + cover letter for a job. Returns (resume_path, cover_path)."""
        from src.libs.resume_and_cover_builder import ResumeFacade, ResumeGenerator, StyleManager
        from src.resume_schemas.resume import Resume

        resume_yaml = RESUME_PATH.read_text(encoding="utf-8")
        resume_object = Resume(resume_yaml)
        style_manager = StyleManager()
        styles = style_manager.get_styles()
        if styles:
            style_manager.set_selected_style(next(iter(styles)))

        output_path = Path("data_folder/output")
        output_path.mkdir(parents=True, exist_ok=True)

        resume_generator = ResumeGenerator()
        resume_generator.set_resume_object(resume_object)

        facade = ResumeFacade(
            api_key=config.llm_api_key,
            style_manager=style_manager,
            resume_generator=resume_generator,
            resume_object=resume_object,
            output_path=output_path,
        )
        # Minimal job context
        from src.job import Job
        j = Job()
        j.role = job.title if hasattr(job, "title") else job.get("title", "")
        j.company = job.company if hasattr(job, "company") else job.get("company", "")
        j.description = job.description if hasattr(job, "description") else job.get("description", "")
        j.link = job.url if hasattr(job, "url") else job.get("url", "")
        facade.job = j

        style_path = style_manager.get_style_path()
        html = resume_generator.create_resume_job_description_text(style_path, j.description)

        # Save as HTML (PDF conversion optional)
        safe_company = "".join(c for c in j.company if c.isalnum() or c in " _-")[:30]
        safe_title = "".join(c for c in j.role if c.isalnum() or c in " _-")[:30]
        fname = f"{safe_company}_{safe_title}_resume.html".replace(" ", "_")
        resume_path = str(output_path / fname)
        Path(resume_path).write_text(html, encoding="utf-8")
        return resume_path, ""
