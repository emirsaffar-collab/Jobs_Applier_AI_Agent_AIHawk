"""Heartbeat-based watchdog for detecting hung bot processes.

Runs as a background ``asyncio.Task``.  The main bot loop calls
``heartbeat()`` on each iteration; the watchdog fires a callback
(or cancels the monitored task) if no heartbeat arrives within
the configured timeout.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from src.logging import logger


class Watchdog:
    """Monitor a long-running async task for hangs.

    Usage::

        wd = Watchdog(timeout=300)
        wd.start(monitored_task)

        # inside the bot loop
        wd.heartbeat()

        # on shutdown
        await wd.stop()
    """

    def __init__(
        self,
        timeout: float = 300.0,
        check_interval: float = 30.0,
        on_hung: Callable[[], Any] | None = None,
    ):
        self.timeout = timeout
        self.check_interval = check_interval
        self._on_hung = on_hung

        self._last_heartbeat: float = time.monotonic()
        self._task: asyncio.Task | None = None
        self._monitored: asyncio.Task | None = None
        self._running = False

        # Health counters
        self.consecutive_failures: int = 0
        self.total_recoveries: int = 0
        self.browser_restarts: int = 0
        self._start_time: float = time.monotonic()

    def heartbeat(self) -> None:
        """Signal that the monitored process is alive."""
        self._last_heartbeat = time.monotonic()

    def record_failure(self) -> None:
        self.consecutive_failures += 1

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def record_recovery(self) -> None:
        self.total_recoveries += 1

    def record_browser_restart(self) -> None:
        self.browser_restarts += 1

    def start(self, monitored_task: asyncio.Task | None = None) -> None:
        """Start the watchdog background loop."""
        self._monitored = monitored_task
        self._running = True
        self._last_heartbeat = time.monotonic()
        self._start_time = time.monotonic()
        self._task = asyncio.create_task(self._loop())
        logger.debug("Watchdog started (timeout={}s, interval={}s)", self.timeout, self.check_interval)

    async def stop(self) -> None:
        """Stop the watchdog."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(self.check_interval)
                if not self._running:
                    break

                elapsed = time.monotonic() - self._last_heartbeat
                if elapsed > self.timeout:
                    logger.error(
                        "Watchdog: no heartbeat for {:.0f}s (timeout={}s) — process may be hung",
                        elapsed,
                        self.timeout,
                    )
                    if self._on_hung:
                        try:
                            result = self._on_hung()
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as exc:
                            logger.warning("Watchdog on_hung callback failed: {}", exc)

                    # Cancel the monitored task as a last resort
                    if self._monitored and not self._monitored.done():
                        logger.warning("Watchdog cancelling hung task")
                        self._monitored.cancel()
                    break
        except asyncio.CancelledError:
            pass

    def get_health(self) -> dict[str, Any]:
        """Return current health metrics."""
        now = time.monotonic()
        return {
            "uptime_seconds": round(now - self._start_time),
            "seconds_since_heartbeat": round(now - self._last_heartbeat),
            "consecutive_failures": self.consecutive_failures,
            "total_recoveries": self.total_recoveries,
            "browser_restarts": self.browser_restarts,
            "watchdog_timeout": self.timeout,
        }
