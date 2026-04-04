"""Structured error hierarchy for the bot automation layer.

Distinguishes retryable transient failures from fatal errors so callers
can decide whether to retry, skip, or abort.
"""


class BotError(Exception):
    """Base class for all bot-specific errors."""


class RetryableError(BotError):
    """Transient failure that may succeed on retry (network, timeout, rate-limit)."""


class FatalError(BotError):
    """Non-recoverable failure — do not retry (auth failure, bad config)."""


class BrowserCrashedError(RetryableError):
    """The Playwright browser or context died unexpectedly."""


class PlatformBlockedError(RetryableError):
    """The job platform blocked access (IP ban, account lock, CAPTCHA wall)."""


class LLMServiceError(RetryableError):
    """LLM API call failed (timeout, rate-limit, server error)."""


class CaptchaError(RetryableError):
    """CAPTCHA detection or solving failed."""


class CircuitOpenError(BotError):
    """Circuit breaker is open — the downstream service is considered unavailable."""

    def __init__(self, name: str, retry_after: float = 0):
        self.breaker_name = name
        self.retry_after = retry_after
        super().__init__(f"Circuit breaker '{name}' is open (retry after {retry_after:.0f}s)")
