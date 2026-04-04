"""Reusable retry decorator with exponential backoff and jitter."""
from __future__ import annotations

import asyncio
import functools
import random
from typing import Any, Callable, TypeVar

from src.logging import logger

F = TypeVar("F", bound=Callable[..., Any])


def async_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: tuple[type[BaseException], ...] = (Exception,),
    on_retry: Callable[[int, Exception], None] | None = None,
) -> Callable[[F], F]:
    """Decorator that retries an async function on specified exceptions.

    Delay formula: ``min(base_delay * backoff_factor ** attempt + jitter, max_delay)``

    Args:
        max_retries: Maximum number of retry attempts (0 = no retry).
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Upper bound on delay between retries.
        backoff_factor: Multiplier applied to delay after each attempt.
        jitter: If True, add random jitter (0–50 % of computed delay).
        retryable_exceptions: Only retry on these exception types.
        on_retry: Optional callback ``(attempt, exception)`` fired before each retry.
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return await fn(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_exc = exc
                    if attempt >= max_retries:
                        break
                    delay = min(base_delay * (backoff_factor ** attempt), max_delay)
                    if jitter:
                        delay += delay * random.uniform(0, 0.5)
                    if on_retry:
                        on_retry(attempt + 1, exc)
                    else:
                        logger.warning(
                            "Retry {}/{} for {} after {:.1f}s — {}",
                            attempt + 1,
                            max_retries,
                            fn.__qualname__,
                            delay,
                            exc,
                        )
                    await asyncio.sleep(delay)
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator
