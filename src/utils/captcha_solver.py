"""CAPTCHA solving integration supporting CAPSolver, 2Captcha, and AntiCaptcha.

Set CAPSOLVER_API_KEY (or TWOCAPTCHA_API_KEY / ANTICAPTCHA_API_KEY) in your
environment and configure CAPTCHA_PROVIDER to select the provider.
When no key is configured the solver simply returns None so the bot can
continue (some platforms won't show CAPTCHAs at all).
"""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

from src.logging import logger

CAPSOLVER_BASE = "https://api.capsolver.com"
TWOCAPTCHA_BASE = "https://api.2captcha.com"
ANTICAPTCHA_BASE = "https://api.anti-captcha.com"

# Supported CAPTCHA task types (CAPSolver names)
TASK_TYPES = {
    "hcaptcha":      "HCaptchaTaskProxyLess",
    "recaptcha_v2":  "ReCaptchaV2TaskProxyLess",
    "recaptcha_v3":  "ReCaptchaV3TaskProxyLess",
    "turnstile":     "AntiTurnstileTaskProxyLess",
}


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class CaptchaProvider(ABC):
    """Common interface for CAPTCHA-solving providers."""

    @property
    @abstractmethod
    def enabled(self) -> bool: ...

    @abstractmethod
    async def solve_hcaptcha(self, website_url: str, site_key: str) -> str | None: ...

    @abstractmethod
    async def solve_recaptcha_v2(self, website_url: str, site_key: str) -> str | None: ...

    @abstractmethod
    async def solve_recaptcha_v3(
        self, website_url: str, site_key: str, page_action: str = ""
    ) -> str | None: ...

    @abstractmethod
    async def solve_turnstile(self, website_url: str, site_key: str) -> str | None: ...

    @abstractmethod
    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# CAPSolver provider (original)
# ---------------------------------------------------------------------------

class CapSolverProvider(CaptchaProvider):
    """Thin async wrapper around the CAPSolver API."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def solve_hcaptcha(self, website_url: str, site_key: str) -> str | None:
        return await self._solve(
            task_type=TASK_TYPES["hcaptcha"],
            website_url=website_url,
            website_key=site_key,
        )

    async def solve_recaptcha_v2(self, website_url: str, site_key: str) -> str | None:
        return await self._solve(
            task_type=TASK_TYPES["recaptcha_v2"],
            website_url=website_url,
            website_key=site_key,
        )

    async def solve_recaptcha_v3(
        self, website_url: str, site_key: str, page_action: str = ""
    ) -> str | None:
        extra: dict[str, Any] = {}
        if page_action:
            extra["pageAction"] = page_action
        return await self._solve(
            task_type=TASK_TYPES["recaptcha_v3"],
            website_url=website_url,
            website_key=site_key,
            **extra,
        )

    async def solve_turnstile(self, website_url: str, site_key: str) -> str | None:
        return await self._solve(
            task_type=TASK_TYPES["turnstile"],
            website_url=website_url,
            website_key=site_key,
        )

    async def _solve(
        self,
        task_type: str,
        website_url: str,
        website_key: str,
        **extra: Any,
    ) -> str | None:
        if not self.enabled:
            logger.debug("CAPTCHA solver not configured — skipping.")
            return None

        client = await self._get_client()
        task: dict[str, Any] = {
            "type": task_type,
            "websiteURL": website_url,
            "websiteKey": website_key,
            **extra,
        }

        try:
            resp = await client.post(
                f"{CAPSOLVER_BASE}/createTask",
                json={"clientKey": self.api_key, "task": task},
            )
            data = resp.json()
        except Exception as exc:
            logger.warning("CAPSolver createTask failed: {}", exc)
            return None

        if data.get("errorId", 0) != 0:
            logger.warning("CAPSolver error: {}", data.get("errorDescription", "unknown"))
            return None

        task_id = data.get("taskId")
        if not task_id:
            logger.warning("CAPSolver returned no taskId")
            return None

        return await self._poll_result(client, task_id, timeout=120)

    async def _poll_result(
        self, client: httpx.AsyncClient, task_id: str, timeout: int = 120
    ) -> str | None:
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            await asyncio.sleep(3)
            try:
                resp = await client.post(
                    f"{CAPSOLVER_BASE}/getTaskResult",
                    json={"clientKey": self.api_key, "taskId": task_id},
                )
                data = resp.json()
            except Exception as exc:
                logger.warning("CAPSolver poll error: {}", exc)
                continue

            status = data.get("status", "")
            if status == "ready":
                solution = data.get("solution", {})
                token = (
                    solution.get("gRecaptchaResponse")
                    or solution.get("token")
                    or solution.get("captcha_response")
                )
                if token:
                    logger.info("CAPTCHA solved (type={}, elapsed={:.1f}s)",
                                data.get("task", {}).get("type", "?"),
                                time.monotonic() - start)
                    return token
                logger.warning("CAPSolver ready but no token in solution: {}", solution)
                return None
            if status == "failed":
                logger.warning("CAPSolver task failed: {}", data.get("errorDescription", ""))
                return None

        logger.warning("CAPSolver timed out after {}s", timeout)
        return None


# Keep the old class name as an alias for backwards compatibility
CaptchaSolver = CapSolverProvider


# ---------------------------------------------------------------------------
# 2Captcha provider
# ---------------------------------------------------------------------------

class TwoCaptchaProvider(CaptchaProvider):
    """CAPTCHA solving via the 2Captcha REST API."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _submit_and_poll(self, params: dict[str, str]) -> str | None:
        if not self.enabled:
            return None
        client = await self._get_client()
        params["key"] = self.api_key
        params["json"] = "1"
        try:
            resp = await client.get(f"{TWOCAPTCHA_BASE}/in.php", params=params)
            data = resp.json()
        except Exception as exc:
            logger.warning("2Captcha submit failed: {}", exc)
            return None
        if data.get("status") != 1:
            logger.warning("2Captcha error: {}", data.get("request", "unknown"))
            return None
        captcha_id = str(data.get("request", ""))
        # Poll every 5 s, max 120 s
        start = time.monotonic()
        while time.monotonic() - start < 120:
            await asyncio.sleep(5)
            try:
                resp = await client.get(
                    f"{TWOCAPTCHA_BASE}/res.php",
                    params={"key": self.api_key, "action": "get", "id": captcha_id, "json": "1"},
                )
                data = resp.json()
            except Exception as exc:
                logger.warning("2Captcha poll error: {}", exc)
                continue
            if data.get("status") == 1:
                return str(data.get("request", ""))
            if data.get("request") not in ("CAPCHA_NOT_READY", "CAPTCHA_NOT_READY"):
                logger.warning("2Captcha error during poll: {}", data.get("request"))
                return None
        logger.warning("2Captcha timed out")
        return None

    async def solve_hcaptcha(self, website_url: str, site_key: str) -> str | None:
        return await self._submit_and_poll(
            {"method": "hcaptcha", "sitekey": site_key, "pageurl": website_url}
        )

    async def solve_recaptcha_v2(self, website_url: str, site_key: str) -> str | None:
        return await self._submit_and_poll(
            {"method": "userrecaptcha", "googlekey": site_key, "pageurl": website_url}
        )

    async def solve_recaptcha_v3(
        self, website_url: str, site_key: str, page_action: str = ""
    ) -> str | None:
        params = {
            "method": "userrecaptcha",
            "version": "v3",
            "googlekey": site_key,
            "pageurl": website_url,
            "min_score": "0.7",
        }
        if page_action:
            params["action"] = page_action
        return await self._submit_and_poll(params)

    async def solve_turnstile(self, website_url: str, site_key: str) -> str | None:
        return await self._submit_and_poll(
            {"method": "turnstile", "sitekey": site_key, "pageurl": website_url}
        )


# ---------------------------------------------------------------------------
# AntiCaptcha provider
# ---------------------------------------------------------------------------

class AntiCaptchaProvider(CaptchaProvider):
    """CAPTCHA solving via the AntiCaptcha API."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _solve_task(self, task: dict[str, Any]) -> str | None:
        if not self.enabled:
            return None
        client = await self._get_client()
        try:
            resp = await client.post(
                f"{ANTICAPTCHA_BASE}/createTask",
                json={"clientKey": self.api_key, "task": task},
            )
            data = resp.json()
        except Exception as exc:
            logger.warning("AntiCaptcha createTask failed: {}", exc)
            return None
        if data.get("errorId", 0) != 0:
            logger.warning("AntiCaptcha error: {}", data.get("errorDescription", "unknown"))
            return None
        task_id = data.get("taskId")
        if not task_id:
            return None
        # Poll every 5 s, max 120 s
        start = time.monotonic()
        while time.monotonic() - start < 120:
            await asyncio.sleep(5)
            try:
                resp = await client.post(
                    f"{ANTICAPTCHA_BASE}/getTaskResult",
                    json={"clientKey": self.api_key, "taskId": task_id},
                )
                data = resp.json()
            except Exception as exc:
                logger.warning("AntiCaptcha poll error: {}", exc)
                continue
            if data.get("status") == "ready":
                sol = data.get("solution", {})
                return (
                    sol.get("gRecaptchaResponse")
                    or sol.get("token")
                    or sol.get("captcha_response")
                )
            if data.get("status") == "failed" or data.get("errorId", 0) != 0:
                logger.warning("AntiCaptcha task failed: {}", data.get("errorDescription", ""))
                return None
        logger.warning("AntiCaptcha timed out")
        return None

    async def solve_hcaptcha(self, website_url: str, site_key: str) -> str | None:
        return await self._solve_task({
            "type": "HCaptchaTaskProxyless",
            "websiteURL": website_url,
            "websiteKey": site_key,
        })

    async def solve_recaptcha_v2(self, website_url: str, site_key: str) -> str | None:
        return await self._solve_task({
            "type": "RecaptchaV2TaskProxyless",
            "websiteURL": website_url,
            "websiteKey": site_key,
        })

    async def solve_recaptcha_v3(
        self, website_url: str, site_key: str, page_action: str = ""
    ) -> str | None:
        task: dict[str, Any] = {
            "type": "RecaptchaV3TaskProxyless",
            "websiteURL": website_url,
            "websiteKey": site_key,
            "minScore": 0.7,
        }
        if page_action:
            task["pageAction"] = page_action
        return await self._solve_task(task)

    async def solve_turnstile(self, website_url: str, site_key: str) -> str | None:
        return await self._solve_task({
            "type": "AntiTurnstileTaskProxyless",
            "websiteURL": website_url,
            "websiteKey": site_key,
        })


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_captcha_solver(provider: str = "capsolver", api_key: str = "") -> CaptchaProvider:
    """Create a CAPTCHA solver for the given provider name.

    Supported provider values: "capsolver", "2captcha", "anticaptcha".
    Falls back to CapSolverProvider for unknown values.
    """
    provider = (provider or "capsolver").lower().strip()
    if provider == "2captcha":
        return TwoCaptchaProvider(api_key=api_key)
    if provider == "anticaptcha":
        return AntiCaptchaProvider(api_key=api_key)
    return CapSolverProvider(api_key=api_key)


# ------------------------------------------------------------------
# Playwright helper — detect and solve CAPTCHAs on a page
# ------------------------------------------------------------------

async def detect_and_solve_captcha(page, solver: CaptchaSolver) -> bool:
    """Detect common CAPTCHA iframes on the current page and solve them.

    Returns True if a CAPTCHA was found and solved, False otherwise.
    """
    if not solver.enabled:
        return False

    url = page.url

    # --- hCaptcha ---
    hcaptcha_frame = await page.query_selector("iframe[src*='hcaptcha.com']")
    if hcaptcha_frame:
        site_key = await _extract_site_key(page, "hcaptcha")
        if site_key:
            token = await solver.solve_hcaptcha(url, site_key)
            if token:
                await _inject_captcha_response(page, token, "hcaptcha")
                return True

    # --- reCAPTCHA ---
    recaptcha_frame = await page.query_selector(
        "iframe[src*='recaptcha'], .g-recaptcha"
    )
    if recaptcha_frame:
        site_key = await _extract_site_key(page, "recaptcha")
        if site_key:
            token = await solver.solve_recaptcha_v2(url, site_key)
            if token:
                await _inject_captcha_response(page, token, "recaptcha")
                return True

    # --- Cloudflare Turnstile ---
    turnstile_frame = await page.query_selector(
        "iframe[src*='challenges.cloudflare.com'], .cf-turnstile"
    )
    if turnstile_frame:
        site_key = await _extract_site_key(page, "turnstile")
        if site_key:
            token = await solver.solve_turnstile(url, site_key)
            if token:
                await _inject_captcha_response(page, token, "turnstile")
                return True

    return False


async def _extract_site_key(page, captcha_type: str) -> str | None:
    """Try to extract the site key from the page DOM."""
    try:
        if captcha_type == "hcaptcha":
            el = await page.query_selector("[data-sitekey]")
            if el:
                return await el.get_attribute("data-sitekey")
            # Fallback: check iframe src
            iframe = await page.query_selector("iframe[src*='hcaptcha.com']")
            if iframe:
                src = await iframe.get_attribute("src") or ""
                for part in src.split("&"):
                    if part.startswith("sitekey="):
                        return part.split("=", 1)[1]

        elif captcha_type == "recaptcha":
            el = await page.query_selector(".g-recaptcha[data-sitekey]")
            if el:
                return await el.get_attribute("data-sitekey")
            iframe = await page.query_selector("iframe[src*='recaptcha']")
            if iframe:
                src = await iframe.get_attribute("src") or ""
                for part in src.split("&"):
                    if part.startswith("k="):
                        return part.split("=", 1)[1]

        elif captcha_type == "turnstile":
            el = await page.query_selector(".cf-turnstile[data-sitekey]")
            if el:
                return await el.get_attribute("data-sitekey")

    except Exception as exc:
        logger.debug("Failed to extract {} site key: {}", captcha_type, exc)
    return None


async def _inject_captcha_response(page, token: str, captcha_type: str) -> None:
    """Inject the solved CAPTCHA token into the page."""
    try:
        if captcha_type == "recaptcha":
            await page.evaluate(
                """(token) => {
                    document.getElementById('g-recaptcha-response').value = token;
                    if (typeof ___grecaptcha_cfg !== 'undefined') {
                        Object.entries(___grecaptcha_cfg.clients).forEach(([k,v]) => {
                            if (v.callback) v.callback(token);
                        });
                    }
                }""",
                token,
            )
        elif captcha_type == "hcaptcha":
            await page.evaluate(
                """(token) => {
                    const textarea = document.querySelector('[name="h-captcha-response"]');
                    if (textarea) textarea.value = token;
                    const el = document.querySelector('[data-hcaptcha-widget-id]');
                    if (el && window.hcaptcha) {
                        hcaptcha.setResponse(token);
                    }
                }""",
                token,
            )
        elif captcha_type == "turnstile":
            await page.evaluate(
                """(token) => {
                    const input = document.querySelector('[name="cf-turnstile-response"]');
                    if (input) input.value = token;
                    if (window.turnstile && window.turnstile._callbacks) {
                        Object.values(window.turnstile._callbacks).forEach(cb => cb(token));
                    }
                }""",
                token,
            )
        logger.debug("Injected {} CAPTCHA response token.", captcha_type)
    except Exception as exc:
        logger.warning("Failed to inject {} CAPTCHA response: {}", captcha_type, exc)
