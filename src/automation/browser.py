"""Playwright browser lifecycle manager with cookie persistence, proxy rotation, and enhanced stealth."""
from __future__ import annotations

import json
import random
from pathlib import Path

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

from src.logging import logger

COOKIES_DIR = Path("data_folder/cookies")

# Pool of realistic user agents to rotate through
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# Realistic viewport sizes
_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 900},
]

# Extended stealth init script
_STEALTH_SCRIPT = """
// Remove webdriver flag
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

// Override plugins to look like a real browser
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// Override languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});

// Prevent headless detection via permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);

// Spoof chrome runtime
window.chrome = { runtime: {} };

// Remove automation-related properties from window
delete window.__playwright;
delete window.__pw_manual;
"""


class BrowserManager:
    """Manages a single persistent Playwright Chromium browser instance.

    Supports per-platform cookie persistence so users stay logged in
    across bot runs without re-entering credentials each time.

    New features:
    - Proxy rotation (list of proxy URLs)
    - User-agent rotation
    - Enhanced stealth (navigator overrides, viewport randomisation)
    """

    def __init__(
        self,
        headless: bool = True,
        proxies: list[str] | None = None,
    ):
        self.headless = headless
        self._proxies = proxies or []
        self._proxy_index = 0
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    def _next_proxy(self) -> dict | None:
        """Round-robin through proxy list. Returns Playwright proxy dict or None."""
        if not self._proxies:
            return None
        proxy_url = self._proxies[self._proxy_index % len(self._proxies)]
        self._proxy_index += 1
        # Parse proxy URL: protocol://user:pass@host:port or protocol://host:port
        proxy: dict[str, str] = {"server": proxy_url}
        if "@" in proxy_url:
            # Extract credentials
            scheme_rest = proxy_url.split("://", 1)
            if len(scheme_rest) == 2:
                scheme, rest = scheme_rest
                cred_host = rest.split("@", 1)
                if len(cred_host) == 2:
                    creds, host = cred_host
                    user_pass = creds.split(":", 1)
                    proxy["server"] = f"{scheme}://{host}"
                    proxy["username"] = user_pass[0]
                    if len(user_pass) > 1:
                        proxy["password"] = user_pass[1]
        logger.debug("Using proxy: {}", proxy.get("server", "none"))
        return proxy

    async def launch(self) -> BrowserContext:
        """Start Playwright and launch a Chromium browser context."""
        self._playwright = await async_playwright().start()

        launch_args = [
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ]

        proxy = self._next_proxy()
        launch_kwargs: dict = {
            "headless": self.headless,
            "args": launch_args,
        }
        if proxy:
            launch_kwargs["proxy"] = proxy

        self._browser = await self._playwright.chromium.launch(**launch_kwargs)

        # Randomise fingerprint per session
        viewport = random.choice(_VIEWPORTS)
        user_agent = random.choice(_USER_AGENTS)

        self._context = await self._browser.new_context(
            viewport=viewport,
            user_agent=user_agent,
            java_script_enabled=True,
            locale="en-US",
        )
        # Enhanced stealth
        await self._context.add_init_script(_STEALTH_SCRIPT)
        logger.info(
            "Browser launched (headless={}, viewport={}x{}, proxy={})",
            self.headless, viewport["width"], viewport["height"],
            "yes" if proxy else "no",
        )
        return self._context

    async def rotate_proxy(self) -> None:
        """Close current browser and relaunch with the next proxy in the pool.

        Useful for recovering from IP-based blocks mid-session.
        """
        if not self._proxies:
            logger.debug("No proxies configured — rotation skipped.")
            return
        logger.info("Rotating proxy...")
        await self.close()
        await self.launch()

    async def new_page(self) -> Page:
        """Open a new page in the current context."""
        if self._context is None:
            await self.launch()
        return await self._context.new_page()

    async def save_cookies(self, platform: str) -> None:
        """Persist current browser cookies for a platform."""
        if self._context is None:
            return
        COOKIES_DIR.mkdir(parents=True, exist_ok=True)
        cookies = await self._context.cookies()
        path = COOKIES_DIR / f"{platform}.json"
        path.write_text(json.dumps(cookies, indent=2))
        logger.info("Saved {} cookies for {}", len(cookies), platform)

    async def load_cookies(self, platform: str) -> bool:
        """Restore saved cookies for a platform. Returns True if found."""
        path = COOKIES_DIR / f"{platform}.json"
        if not path.exists():
            return False
        if self._context is None:
            await self.launch()
        try:
            cookies = json.loads(path.read_text())
            await self._context.add_cookies(cookies)
            logger.info("Loaded {} saved cookies for {}", len(cookies), platform)
            return True
        except Exception as exc:
            logger.warning("Could not load cookies for {}: {}", platform, exc)
            return False

    async def clear_cookies(self, platform: str) -> None:
        """Delete saved cookie file for a platform."""
        path = COOKIES_DIR / f"{platform}.json"
        if path.exists():
            path.unlink()

    async def close(self) -> None:
        """Shut down the browser and Playwright."""
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as exc:
            logger.warning("Error closing browser: {}", exc)
        finally:
            self._context = None
            self._browser = None
            self._playwright = None
