"""Tests for RateLimiter."""
import asyncio
import time

import pytest

from src.automation.rate_limiter import RateLimiter, PlatformWindow


class TestPlatformWindow:
    def test_record_and_count(self):
        pw = PlatformWindow()
        pw.record()
        pw.record()
        assert pw.count_in_window() == 2

    def test_expired_entries_cleaned(self):
        pw = PlatformWindow()
        # Manually insert an old timestamp (older than 24h window)
        pw.timestamps.append(time.monotonic() - 90000)
        pw.record()
        assert pw.count_in_window() == 1


class TestRateLimiter:
    def test_default_limit(self):
        rl = RateLimiter(default_limit=10)
        assert rl.get_limit("linkedin") == 10

    def test_custom_limit(self):
        rl = RateLimiter(limits={"linkedin": 50}, default_limit=10)
        assert rl.get_limit("linkedin") == 50
        assert rl.get_limit("indeed") == 10

    def test_can_apply_under_limit(self):
        rl = RateLimiter(default_limit=3)
        assert rl.can_apply("linkedin") is True
        rl.record_application("linkedin")
        rl.record_application("linkedin")
        assert rl.can_apply("linkedin") is True
        rl.record_application("linkedin")
        assert rl.can_apply("linkedin") is False

    def test_remaining(self):
        rl = RateLimiter(default_limit=5)
        assert rl.remaining("linkedin") == 5
        rl.record_application("linkedin")
        assert rl.remaining("linkedin") == 4

    def test_get_stats(self):
        rl = RateLimiter(default_limit=10)
        rl.record_application("linkedin")
        rl.record_application("linkedin")
        stats = rl.get_stats()
        assert "linkedin" in stats
        assert stats["linkedin"]["applied_24h"] == 2
        assert stats["linkedin"]["remaining"] == 8

    @pytest.mark.asyncio
    async def test_wait_cooldown_no_wait(self):
        rl = RateLimiter(cooldown_minutes=0.001)
        # First call — no prior application, should not wait
        start = time.monotonic()
        await rl.wait_cooldown("linkedin")
        elapsed = time.monotonic() - start
        assert elapsed < 1.0
