"""Retry logic for transient failures."""

import asyncio
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)


def with_retry(
    max_attempts: int = 2,
    backoff_seconds: float = 1.0,
    retry_exceptions: tuple[type[Exception], ...] = (ConnectionError, TimeoutError),
) -> Callable[[Callable], Callable]:
    """Retry decorator for transient network failures.

    Args:
        max_attempts: Maximum retry attempts
        backoff_seconds: Base backoff time (doubles each retry)
        retry_exceptions: Exception types to retry on
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except retry_exceptions as exc:
                    last_exception = exc
                    if attempt < max_attempts - 1:
                        wait_time = backoff_seconds * (2**attempt)
                        logger.warning(
                            "Attempt %d/%d failed, retrying in %.1fs: %s",
                            attempt + 1,
                            max_attempts,
                            wait_time,
                            exc,
                        )
                        await asyncio.sleep(wait_time)
            raise last_exception

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            import time

            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except retry_exceptions as exc:
                    last_exception = exc
                    if attempt < max_attempts - 1:
                        wait_time = backoff_seconds * (2**attempt)
                        logger.warning(
                            "Attempt %d/%d failed, retrying in %.1fs: %s",
                            attempt + 1,
                            max_attempts,
                            wait_time,
                            exc,
                        )
                        time.sleep(wait_time)
            raise last_exception

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
