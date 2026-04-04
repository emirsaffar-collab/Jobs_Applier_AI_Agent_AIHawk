"""Self-healing browser wrapper with automatic crash recovery.

Wraps ``BrowserManager`` so that:
- A dead browser is automatically re-launched before yielding a page.
- Pages are always closed in a ``finally`` block (no resource leaks).
- Playwright crashes during a page's lifetime raise ``BrowserCrashedError``
  so the caller can retry the current operation.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from playwright.async_api import Error as PlaywrightError, Page

from src.automation.browser import BrowserManager
from src.automation.resilience.errors import BrowserCrashedError
from src.automation.resilience.retry import async_retry
from src.logging import logger

# Maximum consecutive browser recovery attempts before giving up.
_MAX_RECOVERY_ATTEMPTS = 3


class ManagedBrowser:
    """Resilient wrapper around ``BrowserManager``.

    Usage::

        mb = ManagedBrowser(BrowserManager(headless=True))
        await mb.launch()

        async with mb.managed_page() as page:
            await page.goto("https://example.com")
            # page is always closed; browser auto-recovers on crash
    """

    def __init__(self, browser: BrowserManager) -> None:
        self._browser = browser
        self._recovery_count = 0

    # ------------------------------------------------------------------
    # Delegated properties / methods
    # ------------------------------------------------------------------

    @property
    def inner(self) -> BrowserManager:
        return self._browser

    async def save_cookies(self, platform: str) -> None:
        await self._browser.save_cookies(platform)

    async def load_cookies(self, platform: str) -> bool:
        return await self._browser.load_cookies(platform)

    async def clear_cookies(self, platform: str) -> None:
        await self._browser.clear_cookies(platform)

    async def rotate_proxy(self) -> None:
        await self._browser.rotate_proxy()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @async_retry(
        max_retries=3,
        base_delay=2.0,
        max_delay=30.0,
        retryable_exceptions=(PlaywrightError, OSError),
    )
    async def launch(self):
        """Launch the browser with retry on transient Playwright errors."""
        return await self._browser.launch()

    async def close(self) -> None:
        await self._browser.close()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def is_healthy(self) -> bool:
        """Return True if the browser context is alive and responsive."""
        try:
            if self._browser._context is None:
                return False
            if self._browser._browser is None or not self._browser._browser.is_connected():
                return False
            # Quick sanity check — accessing pages property
            _ = self._browser._context.pages
            return True
        except Exception:
            return False

    async def ensure_healthy(self) -> None:
        """If the browser is unhealthy, close and re-launch it."""
        if await self.is_healthy():
            return
        logger.warning("Browser unhealthy — attempting recovery ({}/{})",
                        self._recovery_count + 1, _MAX_RECOVERY_ATTEMPTS)
        if self._recovery_count >= _MAX_RECOVERY_ATTEMPTS:
            raise BrowserCrashedError(
                f"Browser recovery failed after {_MAX_RECOVERY_ATTEMPTS} attempts"
            )
        try:
            await self._browser.close()
        except Exception:
            pass
        await self.launch()
        self._recovery_count += 1
        logger.info("Browser recovered successfully (attempt {})", self._recovery_count)

    def reset_recovery_counter(self) -> None:
        """Reset after a successful period of operation."""
        self._recovery_count = 0

    # ------------------------------------------------------------------
    # Managed page context manager
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def managed_page(self) -> Page:  # type: ignore[override]
        """Yield a page that is always cleaned up, with crash recovery.

        On Playwright crash during the ``yield``, the browser is restarted
        and ``BrowserCrashedError`` is raised so the caller can retry.
        """
        await self.ensure_healthy()
        page = await self._browser.new_page()
        try:
            yield page
        except PlaywrightError as exc:
            # Playwright errors often mean the browser died
            healthy = await self.is_healthy()
            if not healthy:
                logger.error("Browser crashed during page operation: {}", exc)
                try:
                    await self._browser.close()
                except Exception:
                    pass
                # Attempt recovery for the *next* call
                try:
                    await self.launch()
                except Exception:
                    pass
                raise BrowserCrashedError(str(exc)) from exc
            raise
        finally:
            try:
                if not page.is_closed():
                    await page.close()
            except Exception:
                pass
