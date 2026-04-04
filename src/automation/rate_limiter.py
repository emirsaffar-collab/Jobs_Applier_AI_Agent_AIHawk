"""Per-platform rate limiting to avoid account bans.

Each platform gets its own sliding-window counter that tracks applications
within the last 24 hours.  The bot pauses automatically when a platform's
daily cap is reached, resuming once the oldest applications fall outside
the window.

Configure in work_preferences.yaml:
    rate_limits:
        linkedin: 100
        indeed: 80
        glassdoor: 50
        ziprecruiter: 60
        dice: 60
        default: 80          # fallback for unlisted platforms
        cooldown_minutes: 5   # pause between applications
"""
from __future__ import annotations

import asyncio
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field

from src.logging import logger

WINDOW_SECONDS = 86400  # 24 hours


@dataclass
class PlatformWindow:
    """Sliding-window tracker for one platform."""
    timestamps: list[float] = field(default_factory=list)

    def record(self) -> None:
        self.timestamps.append(time.monotonic())

    def count_in_window(self) -> int:
        cutoff = time.monotonic() - WINDOW_SECONDS
        self.timestamps = [t for t in self.timestamps if t > cutoff]
        return len(self.timestamps)


class RateLimiter:
    """Enforce per-platform daily application caps with cooldown pauses."""

    def __init__(
        self,
        limits: dict[str, int] | None = None,
        default_limit: int = 80,
        cooldown_minutes: float = 5.0,
    ):
        self._limits = limits or {}
        self._default = default_limit
        self._cooldown = cooldown_minutes * 60  # convert to seconds
        self._windows: dict[str, PlatformWindow] = defaultdict(PlatformWindow)
        self._last_apply: dict[str, float] = {}

    def get_limit(self, platform: str) -> int:
        return self._limits.get(platform, self._default)

    def can_apply(self, platform: str) -> bool:
        """Check if we're under the daily limit for this platform."""
        limit = self.get_limit(platform)
        count = self._windows[platform].count_in_window()
        return count < limit

    def remaining(self, platform: str) -> int:
        limit = self.get_limit(platform)
        count = self._windows[platform].count_in_window()
        return max(0, limit - count)

    def record_application(self, platform: str) -> None:
        """Record that an application was sent on this platform."""
        self._windows[platform].record()
        self._last_apply[platform] = time.monotonic()

    async def wait_cooldown(self, platform: str) -> None:
        """Wait for the cooldown period between applications.

        Adds random jitter (+/- 30%) to avoid predictable timing patterns.
        """
        last = self._last_apply.get(platform, 0)
        elapsed = time.monotonic() - last
        remaining = self._cooldown - elapsed

        if remaining > 0:
            # Add jitter: +/- 30%
            jitter = remaining * random.uniform(-0.3, 0.3)
            wait_time = max(0, remaining + jitter)
            logger.debug(
                "Rate limiter cooldown for {}: {:.1f}s (base={:.1f}s, jitter={:.1f}s)",
                platform, wait_time, remaining, jitter,
            )
            await asyncio.sleep(wait_time)

    def get_stats(self) -> dict[str, dict]:
        """Return per-platform usage stats."""
        result = {}
        for platform, window in self._windows.items():
            count = window.count_in_window()
            limit = self.get_limit(platform)
            result[platform] = {
                "applied_24h": count,
                "limit": limit,
                "remaining": max(0, limit - count),
            }
        return result

    # ------------------------------------------------------------------
    # State serialisation for crash recovery
    # ------------------------------------------------------------------

    def export_state(self) -> dict:
        """Serialize rate-limiter state using wall-clock timestamps.

        Monotonic timestamps are converted to wall-clock equivalents so
        the exported state is meaningful across process restarts.
        """
        mono_now = time.monotonic()
        wall_now = time.time()
        offset = wall_now - mono_now  # wall = mono + offset

        windows: dict[str, list[float]] = {}
        for platform, pw in self._windows.items():
            # Prune before exporting
            pw.count_in_window()
            windows[platform] = [t + offset for t in pw.timestamps]

        last_apply: dict[str, float] = {
            p: t + offset for p, t in self._last_apply.items()
        }
        return {"windows": windows, "last_apply": last_apply}

    def import_state(self, data: dict) -> None:
        """Restore state exported by ``export_state()``.

        Wall-clock timestamps are converted back to monotonic equivalents.
        Timestamps outside the 24-hour window are automatically pruned.
        """
        if not data:
            return
        mono_now = time.monotonic()
        wall_now = time.time()
        offset = wall_now - mono_now  # mono = wall - offset

        for platform, wall_ts in data.get("windows", {}).items():
            mono_ts = [t - offset for t in wall_ts]
            self._windows[platform] = PlatformWindow(timestamps=mono_ts)
            # Prune expired entries
            self._windows[platform].count_in_window()

        for platform, wall_t in data.get("last_apply", {}).items():
            self._last_apply[platform] = wall_t - offset

        logger.info("Rate limiter state restored for {} platform(s)", len(data.get("windows", {})))
