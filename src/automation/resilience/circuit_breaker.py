"""Circuit breaker pattern for external service calls.

Prevents cascading failures by fast-failing when a downstream dependency
(LLM, CAPTCHA solver, job platform) is unresponsive.

States:
    CLOSED   — normal operation, failures counted.
    OPEN     — too many failures, calls rejected immediately.
    HALF_OPEN — after recovery timeout, one probe call is allowed.
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from enum import Enum, auto

from src.automation.resilience.errors import CircuitOpenError
from src.logging import logger


class _State(Enum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


class CircuitBreaker:
    """Named circuit breaker for an external service.

    Usage::

        llm_breaker = CircuitBreaker("llm", failure_threshold=5)

        async with llm_breaker.call():
            result = await call_llm(prompt)
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 2,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = _State.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        return self._state.name

    @property
    def is_closed(self) -> bool:
        return self._state == _State.CLOSED

    @asynccontextmanager
    async def call(self):
        """Context manager that guards an external call.

        Raises ``CircuitOpenError`` immediately when the breaker is open.
        Records success/failure to drive state transitions.
        """
        async with self._lock:
            self._maybe_transition_to_half_open()
            if self._state == _State.OPEN:
                retry_after = self.recovery_timeout - (time.monotonic() - self._last_failure_time)
                raise CircuitOpenError(self.name, max(0, retry_after))

        try:
            yield
        except Exception as exc:
            await self._record_failure(exc)
            raise
        else:
            await self._record_success()

    def _maybe_transition_to_half_open(self) -> None:
        """If OPEN and recovery timeout elapsed, move to HALF_OPEN."""
        if self._state == _State.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                logger.info("Circuit '{}' → HALF_OPEN ({}s since last failure)", self.name, f"{elapsed:.0f}")
                self._state = _State.HALF_OPEN
                self._success_count = 0

    async def _record_failure(self, exc: Exception) -> None:
        async with self._lock:
            self._failure_count += 1
            self._success_count = 0
            self._last_failure_time = time.monotonic()

            if self._state == _State.HALF_OPEN:
                logger.warning("Circuit '{}' → OPEN (probe failed: {})", self.name, exc)
                self._state = _State.OPEN
            elif self._failure_count >= self.failure_threshold:
                logger.warning(
                    "Circuit '{}' → OPEN ({} consecutive failures)",
                    self.name,
                    self._failure_count,
                )
                self._state = _State.OPEN

    async def _record_success(self) -> None:
        async with self._lock:
            self._failure_count = 0

            if self._state == _State.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    logger.info("Circuit '{}' → CLOSED (recovered)", self.name)
                    self._state = _State.CLOSED
                    self._success_count = 0

    async def reset(self) -> None:
        """Manually reset the breaker to CLOSED."""
        async with self._lock:
            self._state = _State.CLOSED
            self._failure_count = 0
            self._success_count = 0
            logger.info("Circuit '{}' manually reset to CLOSED", self.name)
