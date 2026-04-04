"""Resilience primitives: retry, circuit breaker, error classification, and self-healing."""

from src.automation.resilience.errors import (
    BotError,
    BrowserCrashedError,
    CaptchaError,
    CircuitOpenError,
    FatalError,
    LLMServiceError,
    PlatformBlockedError,
    RetryableError,
)
from src.automation.resilience.retry import async_retry
from src.automation.resilience.circuit_breaker import CircuitBreaker

__all__ = [
    "async_retry",
    "BotError",
    "BrowserCrashedError",
    "CaptchaError",
    "CircuitBreaker",
    "CircuitOpenError",
    "FatalError",
    "LLMServiceError",
    "PlatformBlockedError",
    "RetryableError",
]
