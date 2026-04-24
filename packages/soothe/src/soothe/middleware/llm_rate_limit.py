"""Rate limiting middleware for LLM API calls.

This middleware throttles LLM API calls at the model level, not thread level,
allowing multiple threads to run concurrently while limiting actual API request rate.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse

logger = logging.getLogger(__name__)


class LLMRateLimitMiddleware(AgentMiddleware):
    """Rate limiting for LLM API calls using sliding window algorithm.

    This middleware implements rate limiting at the LLM request level, not thread level,
    solving the problem where thread-level blocking caused queries to hang for 30+ seconds.

    Key differences from thread-level rate limiting:
    - Thread-level: Entire thread execution blocked waiting for permit (minutes)
    - LLM-level: Only individual API calls blocked (seconds)
    - Thread-level: Only 2 threads can execute at any time
    - LLM-level: Many threads can run, sharing API permits dynamically

    Example:
        ```python
        from soothe.middleware.llm_rate_limit import LLMRateLimitMiddleware

        middleware = LLMRateLimitMiddleware(
            requests_per_minute=120,
            max_concurrent_requests=10,
            call_timeout_seconds=60,
        )
        ```

    Args:
        requests_per_minute: Maximum API requests per minute (sliding window).
        max_concurrent_requests: Maximum concurrent API requests at any instant.
        call_timeout_seconds: Maximum duration per LLM call before timeout.
    """

    name = "LLMRateLimitMiddleware"

    def __init__(
        self,
        requests_per_minute: int = 120,
        max_concurrent_requests: int = 10,
        call_timeout_seconds: int = 60,
    ) -> None:
        """Initialize rate limiter with sliding window and semaphore.

        Args:
            requests_per_minute: Maximum requests per minute (default: 120).
            max_concurrent_requests: Max concurrent requests (default: 10).
            call_timeout_seconds: Max duration per LLM call (default: 60s).
        """
        super().__init__()
        self._rpm_limit = requests_per_minute
        self._concurrent_limit = max_concurrent_requests
        self._call_timeout = call_timeout_seconds

        # Semaphore for concurrent request limiting
        self._semaphore = asyncio.Semaphore(max_concurrent_requests)

        # Sliding window tracker for RPM limiting
        self._request_times: list[float] = []
        self._window_lock = asyncio.Lock()

        logger.info(
            "LLM rate limiter initialized: rpm=%d, concurrent=%d, timeout=%ds",
            requests_per_minute,
            max_concurrent_requests,
            call_timeout_seconds,
        )

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        """Synchronous wrapper (not used for async LLM calls)."""
        # LangChain LLM calls are async, so this should not be called
        # But we implement it for completeness
        logger.warning("Unexpected synchronous LLM call in async middleware")
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Async wrapper that enforces rate limiting on LLM calls.

        This method:
        1. Acquires semaphore permit (max concurrent requests)
        2. Checks sliding window RPM limit
        3. Makes the actual LLM call
        4. Records request time for sliding window
        5. Releases semaphore permit

        Args:
            request: Model request with messages and parameters.
            handler: Next handler in middleware chain (actual LLM call).

        Returns:
            Model response from LLM.
        """
        # Step 1: Acquire semaphore permit (blocks if too many concurrent requests)
        async with self._semaphore:
            # Step 2: Check and enforce RPM sliding window limit
            await self._enforce_rpm_limit()

            # Step 3: Make the actual LLM call with timeout
            # IG-053: Prevent semaphore monopolization by long-running calls
            logger.debug("LLM rate limiter: making request")
            try:
                response = await asyncio.wait_for(handler(request), timeout=self._call_timeout)
            except TimeoutError:
                logger.error(
                    "LLM call exceeded %ds timeout, releasing semaphore", self._call_timeout
                )
                raise

            # Step 4: Record this request time for sliding window
            await self._record_request_time()

            # Step 5: Semaphore permit released automatically by async with
            return response

    async def _enforce_rpm_limit(self) -> None:
        """Enforce requests-per-minute limit using sliding window.

        This method checks if we've made too many requests in the last minute.
        If so, it calculates how long to wait and blocks until the oldest
        request falls outside the window.
        """
        async with self._window_lock:
            now = time.time()
            window_start = now - 60.0  # 1 minute sliding window

            # Remove requests older than 1 minute
            self._request_times = [t for t in self._request_times if t > window_start]

            # Check if we're at the RPM limit
            if len(self._request_times) >= self._rpm_limit:
                # Calculate wait time until oldest request exits window
                oldest_time = self._request_times[0]
                wait_seconds = oldest_time + 60.0 - now

                if wait_seconds > 0:
                    logger.debug(
                        "LLM rate limiter: waiting %.1fs for RPM limit",
                        wait_seconds,
                    )
                    await asyncio.sleep(wait_seconds)

                    # After waiting, clean up again
                    now = time.time()
                    window_start = now - 60.0
                    self._request_times = [t for t in self._request_times if t > window_start]

    async def _record_request_time(self) -> None:
        """Record the current request time for sliding window tracking."""
        async with self._window_lock:
            self._request_times.append(time.time())

    def get_stats(self) -> dict[str, Any]:
        """Get current rate limiting statistics.

        Returns:
            Dictionary with current semaphore usage and request count.
        """
        now = time.time()
        window_start = now - 60.0
        recent_requests = [t for t in self._request_times if t > window_start]

        return {
            "concurrent_limit": self._concurrent_limit,
            "rpm_limit": self._rpm_limit,
            "requests_in_last_minute": len(recent_requests),
            "semaphore_available": self._semaphore._value,  # Available permits
        }
