"""Rate limiting middleware for LLM API calls.

This middleware throttles LLM API calls at the model level, not thread level,
allowing multiple threads to run concurrently while limiting actual API request rate.

IG-258 Phase 2: Thread-local rate limiting to prevent cross-thread contention.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse

logger = logging.getLogger(__name__)


@dataclass
class ThreadBudget:
    """Thread-local RPM budget for fair distribution (IG-258 Phase 2).

    Each thread has independent:
    - RPM budget (fair share of global limit)
    - Semaphore (no cross-thread starvation)
    - Sliding window tracker

    Args:
        rpm_limit: Requests per minute for this thread.
        semaphore_max: Max concurrent requests for this thread.
    """

    rpm_limit: int
    semaphore_max: int
    request_times: list[float] = field(default_factory=list)
    semaphore: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        """Initialize thread-local semaphore."""
        self.semaphore = asyncio.Semaphore(self.semaphore_max)

    async def wait_for_rpm_slot(self) -> None:
        """Wait for RPM slot (thread-local, no cross-thread blocking).

        This method only blocks the calling thread, not all threads.
        """
        now = time.time()
        # Remove requests older than 60 seconds
        self.request_times = [t for t in self.request_times if now - t < 60.0]

        if len(self.request_times) >= self.rpm_limit:
            oldest = self.request_times[0]
            wait_seconds = oldest + 60.0 - now
            if wait_seconds > 0:
                logger.debug(
                    "Thread budget: waiting %.1fs for RPM slot (thread-local)",
                    wait_seconds,
                )
                await asyncio.sleep(wait_seconds)  # Only blocks THIS thread

                # After waiting, clean up again
                now = time.time()
                self.request_times = [t for t in self.request_times if now - t < 60.0]

    def record_request(self) -> float:
        """Record request time and return timestamp."""
        now = time.time()
        self.request_times.append(now)
        return now

    def get_stats(self) -> dict[str, Any]:
        """Get thread-local statistics."""
        now = time.time()
        recent_requests = [t for t in self.request_times if now - t < 60.0]
        return {
            "rpm_limit": self.rpm_limit,
            "requests_in_last_minute": len(recent_requests),
            "semaphore_available": self.semaphore._value,
        }


class LLMRateLimitMiddleware(AgentMiddleware):
    """Rate limiting for LLM API calls using thread-local budgets (IG-258 Phase 2).

    Phase 2 optimization: Thread-local RPM budgets prevent cross-thread contention.
    Each thread gets a fair share of the global RPM limit, eliminating cascading
    delays when one thread hits the limit.

    Key improvements over global rate limiting:
    - Global: All threads compete for shared RPM → one thread at limit blocks ALL
    - Thread-local: Each thread has independent budget → isolation, no cross-blocking
    - Global: One slow call monopolizes semaphore for 60s → others starve
    - Thread-local: Per-thread semaphore → no starvation, fair distribution

    Example:
        ```python
        from soothe.middleware.llm_rate_limit import LLMRateLimitMiddleware

        middleware = LLMRateLimitMiddleware(
            requests_per_minute=120,
            max_concurrent_requests_per_thread=10,
            call_timeout_seconds=60,
            thread_local=True,  # IG-258 Phase 2
        )
        ```

    Args:
        requests_per_minute: Global RPM limit (distributed across threads).
        max_concurrent_requests_per_thread: Max concurrent per thread (Phase 2).
        call_timeout_seconds: Maximum duration per LLM call before timeout.
        thread_local: Enable thread-local budgets (Phase 2, default True).
    """

    name = "LLMRateLimitMiddleware"

    def __init__(
        self,
        requests_per_minute: int = 120,
        max_concurrent_requests_per_thread: int = 10,
        call_timeout_seconds: int = 60,
        thread_local: bool = True,  # IG-258 Phase 2
    ) -> None:
        """Initialize rate limiter with thread-local budgets (Phase 2).

        Args:
            requests_per_minute: Global RPM limit (default: 120).
            max_concurrent_requests_per_thread: Max concurrent per thread (Phase 2, default: 10).
            call_timeout_seconds: Max duration per LLM call (default: 60s).
            thread_local: Enable thread-local budgets (Phase 2, default True).
        """
        super().__init__()
        self._rpm_limit_global = requests_per_minute
        self._concurrent_limit_per_thread = max_concurrent_requests_per_thread
        self._call_timeout = call_timeout_seconds
        self._thread_local_enabled = thread_local

        if thread_local:
            # Thread-local budgets (Phase 2)
            self._thread_budgets: dict[str, ThreadBudget] = {}
            self._budget_lock = asyncio.Lock()  # Only for budget allocation

            logger.info(
                "LLM rate limiter initialized (thread-local): global_rpm=%d, "
                "per_thread_concurrent=%d, timeout=%ds",
                requests_per_minute,
                max_concurrent_requests_per_thread,
                call_timeout_seconds,
            )
        else:
            # Legacy global mode (fallback)
            self._semaphore = asyncio.Semaphore(max_concurrent_requests_per_thread)
            self._request_times: list[float] = []
            self._window_lock = asyncio.Lock()

            logger.info(
                "LLM rate limiter initialized (global): rpm=%d, concurrent=%d, timeout=%ds",
                requests_per_minute,
                max_concurrent_requests_per_thread,
                call_timeout_seconds,
            )

    async def _get_thread_budget(self, thread_id: str) -> ThreadBudget:
        """Get or create thread-local budget with fair distribution (Phase 2).

        Fair distribution: global RPM / active threads
        Each thread gets independent budget, preventing cross-thread blocking.

        Args:
            thread_id: Thread identifier for budget allocation.

        Returns:
            ThreadBudget with fair share of global RPM limit.
        """
        async with self._budget_lock:
            if thread_id not in self._thread_budgets:
                # Fair distribution: global RPM / active threads
                active_threads = len(self._thread_budgets)
                thread_rpm = max(self._rpm_limit_global // (active_threads + 1), 10)  # Min 10 RPM

                self._thread_budgets[thread_id] = ThreadBudget(
                    rpm_limit=thread_rpm,
                    semaphore_max=self._concurrent_limit_per_thread,
                )

                logger.info(
                    "Thread budget created: thread_id=%s rpm=%d/%d active_threads=%d",
                    thread_id,
                    thread_rpm,
                    self._rpm_limit_global,
                    active_threads + 1,
                )

            return self._thread_budgets[thread_id]

    async def _redistribute_budgets(self) -> None:
        """Redistribute RPM budgets when threads exit (Phase 2).

        Called when thread budget is cleaned up to redistribute
        freed RPM budget to remaining active threads.
        """
        async with self._budget_lock:
            active_threads = len(self._thread_budgets)
            if active_threads > 0:
                thread_rpm = max(self._rpm_limit_global // active_threads, 10)

                for thread_id, budget in self._thread_budgets.items():
                    budget.rpm_limit = thread_rpm

                logger.info(
                    "Budgets redistributed: rpm_per_thread=%d active_threads=%d",
                    thread_rpm,
                    active_threads,
                )

    def cleanup_thread_budget(self, thread_id: str) -> None:
        """Cleanup thread budget when thread ends (Phase 2).

        Args:
            thread_id: Thread identifier to cleanup.
        """
        if thread_id in self._thread_budgets:
            del self._thread_budgets[thread_id]
            logger.info("Thread budget removed: thread_id=%s", thread_id)

            # Schedule redistribution (async)
            asyncio.create_task(self._redistribute_budgets())

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
        """Async wrapper with thread-local rate limiting (Phase 2).

        Phase 2 improvements:
        - Thread-local budget isolation (no cross-thread blocking)
        - Per-thread semaphore (no starvation from slow calls)
        - Fair RPM distribution across active threads

        Args:
            request: Model request with messages and parameters.
            handler: Next handler in middleware chain (actual LLM call).

        Returns:
            Model response from LLM.
        """
        # Get thread_id from request context (if available)
        thread_id = getattr(request, "thread_id", "default")

        if self._thread_local_enabled:
            # Phase 2: Thread-local rate limiting
            budget = await self._get_thread_budget(thread_id)

            # Use thread-local semaphore (no cross-thread contention)
            async with budget.semaphore:
                # Thread-local RPM check (only blocks this thread)
                await budget.wait_for_rpm_slot()

                # Make LLM call with timeout
                logger.debug("LLM rate limiter: making request (thread_id=%s)", thread_id)
                try:
                    response = await asyncio.wait_for(handler(request), timeout=self._call_timeout)
                except TimeoutError:
                    logger.error(
                        "LLM call exceeded %ds timeout (thread_id=%s)",
                        self._call_timeout,
                        thread_id,
                    )
                    raise

                # Record request time in thread-local window
                budget.record_request()

                return response
        else:
            # Legacy global mode (fallback)
            async with self._semaphore:
                await self._enforce_rpm_limit_global()

                logger.debug("LLM rate limiter: making request (global mode)")
                try:
                    response = await asyncio.wait_for(handler(request), timeout=self._call_timeout)
                except TimeoutError:
                    logger.error("LLM call exceeded %ds timeout", self._call_timeout)
                    raise

                await self._record_request_time_global()

                return response

    async def _enforce_rpm_limit_global(self) -> None:
        """Legacy global RPM enforcement (fallback mode)."""
        async with self._window_lock:
            now = time.time()
            window_start = now - 60.0

            self._request_times = [t for t in self._request_times if t > window_start]

            if len(self._request_times) >= self._rpm_limit_global:
                oldest_time = self._request_times[0]
                wait_seconds = oldest_time + 60.0 - now

                if wait_seconds > 0:
                    logger.debug(
                        "LLM rate limiter: waiting %.1fs for RPM limit (global)",
                        wait_seconds,
                    )
                    await asyncio.sleep(wait_seconds)

                    now = time.time()
                    window_start = now - 60.0
                    self._request_times = [t for t in self._request_times if t > window_start]

    async def _record_request_time_global(self) -> None:
        """Legacy global request recording (fallback mode)."""
        async with self._window_lock:
            self._request_times.append(time.time())

    def get_stats(self) -> dict[str, Any]:
        """Get rate limiting statistics.

        Returns:
            Dictionary with thread-local or global statistics.
        """
        if self._thread_local_enabled:
            # Phase 2: Thread-local statistics
            thread_stats = {}
            for thread_id, budget in self._thread_budgets.items():
                thread_stats[thread_id] = budget.get_stats()

            return {
                "mode": "thread_local",
                "global_rpm_limit": self._rpm_limit_global,
                "per_thread_concurrent_limit": self._concurrent_limit_per_thread,
                "active_threads": len(self._thread_budgets),
                "thread_budgets": thread_stats,
            }
        else:
            # Legacy global statistics
            now = time.time()
            window_start = now - 60.0
            recent_requests = [t for t in self._request_times if t > window_start]

            return {
                "mode": "global",
                "concurrent_limit": self._concurrent_limit_per_thread,
                "rpm_limit": self._rpm_limit_global,
                "requests_in_last_minute": len(recent_requests),
                "semaphore_available": self._semaphore._value,
            }
