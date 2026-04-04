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

    def test_record_application_persists_to_tracker(self, tmp_path):
        """record_application should write an event to the tracker DB."""
        from src.automation.application_tracker import ApplicationTracker
        tracker = ApplicationTracker(db_path=tmp_path / "rl.db")
        rl = RateLimiter(default_limit=50)
        rl.record_application("linkedin", tracker)
        rl.record_application("linkedin", tracker)
        events = tracker.get_rate_limit_events("linkedin", since_ts=0)
        assert len(events) == 2

    def test_load_from_db_restores_counts(self, tmp_path):
        """A new RateLimiter loaded from DB should reflect previously-recorded events."""
        from src.automation.application_tracker import ApplicationTracker
        import time as _time

        tracker = ApplicationTracker(db_path=tmp_path / "rl2.db")
        # Simulate 3 applications recorded in a previous session
        for _ in range(3):
            tracker.add_rate_limit_event("linkedin", _time.time())

        # Create a fresh limiter and load from DB
        rl2 = RateLimiter(default_limit=5)
        rl2.load_from_db(tracker)
        assert rl2.remaining("linkedin") == 2  # 5 - 3 = 2

    def test_prune_rate_limit_events(self, tmp_path):
        """prune_rate_limit_events removes old rows."""
        from src.automation.application_tracker import ApplicationTracker
        import time as _time

        tracker = ApplicationTracker(db_path=tmp_path / "rl3.db")
        old_ts = _time.time() - 90000  # older than 24 h
        recent_ts = _time.time() - 1000
        tracker.add_rate_limit_event("linkedin", old_ts)
        tracker.add_rate_limit_event("linkedin", recent_ts)
        tracker.prune_rate_limit_events()
        events = tracker.get_rate_limit_events("linkedin", since_ts=0)
        assert len(events) == 1  # only the recent one remains
