"""Tests for the resilience primitives: retry, circuit breaker, checkpoint, watchdog."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# retry
# ---------------------------------------------------------------------------
from src.automation.resilience.retry import async_retry
from src.automation.resilience.errors import (
    BotError,
    BrowserCrashedError,
    CircuitOpenError,
    FatalError,
    LLMServiceError,
    RetryableError,
)


class TestAsyncRetry:
    """Tests for the async_retry decorator."""

    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        call_count = 0

        @async_retry(max_retries=3, base_delay=0.01)
        async def succeeds():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeeds()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure_then_succeeds(self):
        call_count = 0

        @async_retry(max_retries=3, base_delay=0.01)
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "recovered"

        result = await flaky()
        assert result == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        @async_retry(max_retries=2, base_delay=0.01)
        async def always_fails():
            raise TimeoutError("timeout")

        with pytest.raises(TimeoutError, match="timeout"):
            await always_fails()

    @pytest.mark.asyncio
    async def test_non_retryable_exception_propagates_immediately(self):
        call_count = 0

        @async_retry(max_retries=3, base_delay=0.01, retryable_exceptions=(ConnectionError,))
        async def fatal():
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError):
            await fatal()
        assert call_count == 1  # no retry

    @pytest.mark.asyncio
    async def test_on_retry_callback(self):
        attempts = []

        def tracker(attempt, exc):
            attempts.append((attempt, str(exc)))

        @async_retry(max_retries=2, base_delay=0.01, on_retry=tracker)
        async def flaky():
            raise RuntimeError("oops")

        with pytest.raises(RuntimeError):
            await flaky()

        assert len(attempts) == 2
        assert attempts[0][0] == 1
        assert attempts[1][0] == 2

    @pytest.mark.asyncio
    async def test_exponential_backoff_increases(self):
        """Verify delays increase (rough check via timing)."""
        call_times = []

        @async_retry(max_retries=3, base_delay=0.05, backoff_factor=2.0, jitter=False)
        async def timed_fail():
            call_times.append(time.monotonic())
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            await timed_fail()

        assert len(call_times) == 4  # 1 initial + 3 retries
        # Second delay should be >= first delay
        delay1 = call_times[2] - call_times[1]
        delay0 = call_times[1] - call_times[0]
        assert delay1 >= delay0 * 1.5  # allowing some slack


# ---------------------------------------------------------------------------
# circuit breaker
# ---------------------------------------------------------------------------
from src.automation.resilience.circuit_breaker import CircuitBreaker


class TestCircuitBreaker:
    """Tests for the CircuitBreaker state machine."""

    @pytest.mark.asyncio
    async def test_starts_closed(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        assert cb.state == "CLOSED"
        assert cb.is_closed

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60)

        for _ in range(3):
            with pytest.raises(RuntimeError):
                async with cb.call():
                    raise RuntimeError("fail")

        assert cb.state == "OPEN"

    @pytest.mark.asyncio
    async def test_open_rejects_calls(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=999)

        with pytest.raises(RuntimeError):
            async with cb.call():
                raise RuntimeError("fail")

        assert cb.state == "OPEN"
        with pytest.raises(CircuitOpenError):
            async with cb.call():
                pass  # should not reach here

    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.05, success_threshold=1)

        with pytest.raises(RuntimeError):
            async with cb.call():
                raise RuntimeError("fail")

        assert cb.state == "OPEN"
        await asyncio.sleep(0.1)

        # Next call should be allowed (HALF_OPEN)
        async with cb.call():
            pass  # success

        assert cb.state == "CLOSED"

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.05)

        with pytest.raises(RuntimeError):
            async with cb.call():
                raise RuntimeError("fail")

        await asyncio.sleep(0.1)

        with pytest.raises(RuntimeError):
            async with cb.call():
                raise RuntimeError("fail again")

        assert cb.state == "OPEN"

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self):
        cb = CircuitBreaker("test", failure_threshold=3)

        # Two failures
        for _ in range(2):
            with pytest.raises(RuntimeError):
                async with cb.call():
                    raise RuntimeError("fail")

        # One success resets
        async with cb.call():
            pass

        assert cb.state == "CLOSED"

        # Need 3 more failures to open
        for _ in range(2):
            with pytest.raises(RuntimeError):
                async with cb.call():
                    raise RuntimeError("fail")
        assert cb.state == "CLOSED"

    @pytest.mark.asyncio
    async def test_manual_reset(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=999)

        with pytest.raises(RuntimeError):
            async with cb.call():
                raise RuntimeError("fail")

        assert cb.state == "OPEN"
        await cb.reset()
        assert cb.state == "CLOSED"


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------


class TestErrorHierarchy:
    def test_retryable_is_bot_error(self):
        assert issubclass(RetryableError, BotError)

    def test_fatal_is_bot_error(self):
        assert issubclass(FatalError, BotError)

    def test_browser_crashed_is_retryable(self):
        assert issubclass(BrowserCrashedError, RetryableError)

    def test_llm_service_is_retryable(self):
        assert issubclass(LLMServiceError, RetryableError)

    def test_circuit_open_is_bot_error(self):
        exc = CircuitOpenError("test", retry_after=30)
        assert isinstance(exc, BotError)
        assert exc.breaker_name == "test"
        assert exc.retry_after == 30


# ---------------------------------------------------------------------------
# checkpoint
# ---------------------------------------------------------------------------
from src.automation.resilience.checkpoint import CheckpointManager


class TestCheckpoint:
    def test_save_load_roundtrip(self, tmp_path):
        db = tmp_path / "test_cp.db"
        mgr = CheckpointManager(db_path=db)

        mgr.save(
            session_id="abc123",
            platform_index=2,
            job_index=5,
            stats={"applied": 10, "skipped": 3, "failed": 1},
            rate_limiter_state={"windows": {"linkedin": [1.0, 2.0]}, "last_apply": {"linkedin": 3.0}},
        )

        cp = mgr.load("abc123")
        assert cp is not None
        assert cp.session_id == "abc123"
        assert cp.platform_index == 2
        assert cp.job_index == 5
        assert cp.stats["applied"] == 10
        assert cp.rate_limiter_state["windows"]["linkedin"] == [1.0, 2.0]
        mgr.close()

    def test_load_latest_without_session_id(self, tmp_path):
        db = tmp_path / "test_cp.db"
        mgr = CheckpointManager(db_path=db)

        mgr.save(session_id="old", platform_index=0, job_index=0)
        mgr.save(session_id="new", platform_index=1, job_index=10)

        cp = mgr.load()
        assert cp is not None
        assert cp.session_id == "new"
        mgr.close()

    def test_clear(self, tmp_path):
        db = tmp_path / "test_cp.db"
        mgr = CheckpointManager(db_path=db)

        mgr.save(session_id="abc", platform_index=0, job_index=0)
        mgr.clear("abc")
        assert mgr.load("abc") is None
        mgr.close()

    def test_upsert(self, tmp_path):
        db = tmp_path / "test_cp.db"
        mgr = CheckpointManager(db_path=db)

        mgr.save(session_id="abc", platform_index=0, job_index=0, stats={"applied": 1})
        mgr.save(session_id="abc", platform_index=1, job_index=5, stats={"applied": 5})

        cp = mgr.load("abc")
        assert cp.platform_index == 1
        assert cp.stats["applied"] == 5
        mgr.close()

    def test_clear_old(self, tmp_path):
        db = tmp_path / "test_cp.db"
        mgr = CheckpointManager(db_path=db)

        # Manually insert an old entry
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO checkpoints (session_id, platform_idx, job_idx, stats_json, rl_state_json, updated_at) "
            "VALUES (?, 0, 0, '{}', '{}', ?)",
            ("old_session", time.time() - 72 * 3600),
        )
        conn.commit()
        conn.close()

        deleted = mgr.clear_old(max_age_hours=48)
        assert deleted >= 1
        assert mgr.load("old_session") is None
        mgr.close()


# ---------------------------------------------------------------------------
# watchdog
# ---------------------------------------------------------------------------
from src.automation.resilience.watchdog import Watchdog


class TestWatchdog:
    @pytest.mark.asyncio
    async def test_heartbeat_prevents_timeout(self):
        wd = Watchdog(timeout=0.3, check_interval=0.1)
        wd.start()

        for _ in range(5):
            await asyncio.sleep(0.08)
            wd.heartbeat()

        await wd.stop()
        # If we get here, the watchdog didn't fire — success

    @pytest.mark.asyncio
    async def test_hung_detection_fires_callback(self):
        fired = []

        def on_hung():
            fired.append(True)

        wd = Watchdog(timeout=0.15, check_interval=0.05, on_hung=on_hung)
        wd.start()

        # Don't heartbeat — let it time out
        await asyncio.sleep(0.5)
        await wd.stop()

        assert len(fired) >= 1

    @pytest.mark.asyncio
    async def test_health_metrics(self):
        wd = Watchdog(timeout=10)
        wd.start()
        wd.heartbeat()
        wd.record_failure()
        wd.record_failure()
        wd.record_browser_restart()

        health = wd.get_health()
        assert health["consecutive_failures"] == 2
        assert health["browser_restarts"] == 1
        assert "uptime_seconds" in health
        await wd.stop()

    @pytest.mark.asyncio
    async def test_record_success_resets_failures(self):
        wd = Watchdog(timeout=10)
        wd.record_failure()
        wd.record_failure()
        wd.record_success()
        assert wd.consecutive_failures == 0


# ---------------------------------------------------------------------------
# rate_limiter export/import
# ---------------------------------------------------------------------------
from src.automation.rate_limiter import RateLimiter


class TestRateLimiterSerialization:
    def test_export_import_roundtrip(self):
        rl = RateLimiter(default_limit=50, cooldown_minutes=1)

        # Record some applications
        rl.record_application("linkedin")
        rl.record_application("linkedin")
        rl.record_application("indeed")

        state = rl.export_state()
        assert "windows" in state
        assert "last_apply" in state
        assert len(state["windows"]["linkedin"]) == 2
        assert len(state["windows"]["indeed"]) == 1

        # Restore into a fresh limiter
        rl2 = RateLimiter(default_limit=50, cooldown_minutes=1)
        rl2.import_state(state)

        assert rl2._windows["linkedin"].count_in_window() == 2
        assert rl2._windows["indeed"].count_in_window() == 1

    def test_import_empty_state(self):
        rl = RateLimiter()
        rl.import_state({})  # should not crash
        rl.import_state(None)  # should not crash
