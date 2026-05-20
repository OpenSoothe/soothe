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

from soothe.utils.token_counting import estimate_content_chars

logger = logging.getLogger(__name__)

# Extra wall-clock seconds per this many estimated prompt characters (IG-301).
_CHARS_PER_EXTRA_TIMEOUT_SECOND = 400


def estimate_model_request_prompt_chars(request: ModelRequest[Any]) -> int:
    """Sum system prompt and user/tool message text lengths for timeout scaling (IG-301)."""
    total = 0
    try:
        sys_text = request.system_prompt
        if sys_text:
            total += len(sys_text)
    except Exception:  # noqa: BLE001
        pass
    for msg in request.messages:
        try:
            total += estimate_content_chars(getattr(msg, "content", None))
        except Exception:  # noqa: BLE001
            continue
    return total


def compute_effective_llm_call_timeout(
    *,
    base_seconds: int,
    max_seconds: int,
    prompt_char_estimate: int,
    adaptive: bool,
) -> int:
    """Compute per-call timeout with optional scaling for large prompts (IG-301).

    Args:
        base_seconds: Configured floor (``llm_call_timeout_seconds``).
        max_seconds: Configured ceiling (``llm_call_timeout_max_seconds``).
        prompt_char_estimate: Estimated input characters for this request.
        adaptive: When False, return ``base_seconds`` only.

    Returns:
        Timeout in whole seconds, clamped to ``[base_seconds, max_seconds]``.
    """
    cap = max(max_seconds, base_seconds)
    if not adaptive or prompt_char_estimate <= 0:
        return min(base_seconds, cap)
    extra = prompt_char_estimate // _CHARS_PER_EXTRA_TIMEOUT_SECOND
    return min(cap, max(base_seconds, base_seconds + extra))


class EnhancedTimeoutError(TimeoutError):
    """Timeout error with retry and prompt metadata for better error handling.

    Provides context about retry attempts, timeout duration, and prompt size
    to enable better error classification, user notifications, and planner revision.

    Attributes:
        timeout_seconds: Final timeout duration used.
        retries: Number of retry attempts made.
        prompt_chars: Estimated prompt character count.
        thread_id: Thread where timeout occurred.

    Example:
        >>> exc = EnhancedTimeoutError(
        ...     timeout_seconds=480, retries=2, prompt_chars=96000, thread_id="thread-1"
        ... )
        >>> str(exc)
        "LLM call timed out after 2 retries (480s final timeout) - large prompt (96,000 chars)"
    """

    def __init__(
        self,
        timeout_seconds: int,
        retries: int,
        prompt_chars: int,
        thread_id: str,
    ) -> None:
        """Initialize enhanced timeout error with metadata.

        Args:
            timeout_seconds: Final timeout duration used (seconds).
            retries: Number of retry attempts made.
            prompt_chars: Estimated prompt character count.
            thread_id: Thread where timeout occurred.
        """
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.prompt_chars = prompt_chars
        self.thread_id = thread_id

        # Build message with metadata
        parts = [
            f"LLM call timed out after {retries} retries",
            f"({timeout_seconds}s final timeout)",
        ]
        if prompt_chars > 50000:
            parts.append(f"- large prompt ({prompt_chars:,} chars)")

        msg = " ".join(parts)
        super().__init__(msg)


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
            call_timeout_max_seconds=600,
            call_timeout_adaptive=True,
            thread_local=True,  # IG-258 Phase 2
            retry_on_timeout=True,  # IG-295
            max_timeout_retries=2,  # IG-295
            timeout_retry_multiplier=2.0,  # IG-295
        )
        ```

    Args:
        requests_per_minute: Global RPM limit (distributed across threads).
        max_concurrent_requests_per_thread: Max concurrent per thread (Phase 2).
        call_timeout_seconds: Floor duration per LLM call before timeout.
        call_timeout_max_seconds: Ceiling when adaptive scaling is enabled (IG-301).
        call_timeout_adaptive: Scale timeout from the floor by prompt size (IG-301).
        thread_local: Enable thread-local budgets (Phase 2, default True).
        retry_on_timeout: Enable retry with timeout escalation (IG-295, default True).
        max_timeout_retries: Max retry attempts after timeout (IG-295, default 2).
        timeout_retry_multiplier: Timeout multiplier on retry (IG-295, default 2.0).
    """

    name = "LLMRateLimitMiddleware"

    def __init__(
        self,
        requests_per_minute: int = 120,
        max_concurrent_requests_per_thread: int = 10,
        call_timeout_seconds: int = 60,
        call_timeout_max_seconds: int = 600,
        call_timeout_adaptive: bool = True,
        thread_local: bool = True,  # IG-258 Phase 2
        retry_on_timeout: bool = True,  # IG-295
        max_timeout_retries: int = 2,  # IG-295
        timeout_retry_multiplier: float = 2.0,  # IG-295
    ) -> None:
        """Initialize rate limiter with thread-local budgets and retry (Phase 2, IG-295).

        Args:
            requests_per_minute: Global RPM limit (default: 120).
            max_concurrent_requests_per_thread: Max concurrent per thread (Phase 2, default: 10).
            call_timeout_seconds: Floor max duration per LLM call (default: 60s).
            call_timeout_max_seconds: Ceiling when adaptive (default: 600s, IG-301).
            call_timeout_adaptive: Scale timeout from floor by prompt size (IG-301).
            thread_local: Enable thread-local budgets (Phase 2, default True).
            retry_on_timeout: Enable retry with timeout escalation (IG-295, default True).
            max_timeout_retries: Max retry attempts after timeout (IG-295, default 2).
            timeout_retry_multiplier: Timeout multiplier on retry (IG-295, default 2.0).
        """
        super().__init__()
        self._rpm_limit_global = requests_per_minute
        self._concurrent_limit_per_thread = max_concurrent_requests_per_thread
        self._call_timeout = call_timeout_seconds
        self._call_timeout_max = max(call_timeout_max_seconds, call_timeout_seconds)
        self._call_timeout_adaptive = call_timeout_adaptive
        self._thread_local_enabled = thread_local

        # Retry configuration (IG-295)
        self._retry_on_timeout = retry_on_timeout
        self._max_timeout_retries = max_timeout_retries
        self._timeout_retry_multiplier = timeout_retry_multiplier

        if thread_local:
            # Thread-local budgets (Phase 2)
            self._thread_budgets: dict[str, ThreadBudget] = {}
            self._budget_lock = asyncio.Lock()  # Only for budget allocation

            logger.info(
                "LLM rate limiter initialized (thread-local): global_rpm=%d, "
                "per_thread_concurrent=%d, timeout_floor=%ds timeout_cap=%ds adaptive=%s "
                "retry=%s max_retries=%d retry_multiplier=%.1f",
                requests_per_minute,
                max_concurrent_requests_per_thread,
                call_timeout_seconds,
                self._call_timeout_max,
                call_timeout_adaptive,
                retry_on_timeout,
                max_timeout_retries,
                timeout_retry_multiplier,
            )
        else:
            # Legacy global mode (fallback)
            self._semaphore = asyncio.Semaphore(max_concurrent_requests_per_thread)
            self._request_times: list[float] = []
            self._window_lock = asyncio.Lock()

            logger.info(
                "LLM rate limiter initialized (global): rpm=%d, concurrent=%d, "
                "timeout_floor=%ds timeout_cap=%ds adaptive=%s "
                "retry=%s max_retries=%d retry_multiplier=%.1f",
                requests_per_minute,
                max_concurrent_requests_per_thread,
                call_timeout_seconds,
                self._call_timeout_max,
                call_timeout_adaptive,
                retry_on_timeout,
                max_timeout_retries,
                timeout_retry_multiplier,
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

    def _effective_call_timeout(self, request: ModelRequest[Any]) -> int:
        """Per-request timeout (adaptive for large prompts, IG-301)."""
        est = estimate_model_request_prompt_chars(request)
        return compute_effective_llm_call_timeout(
            base_seconds=self._call_timeout,
            max_seconds=self._call_timeout_max,
            prompt_char_estimate=est,
            adaptive=self._call_timeout_adaptive,
        )

    def _calculate_retry_timeout(
        self,
        base_timeout: int,
        attempt: int,
        request: ModelRequest[Any],
    ) -> int:
        """Calculate timeout with escalation on retry (IG-295).

        Timeout escalates by multiplier on each retry attempt, capped at max.
        Adaptive scaling still applies on top of escalated base.

        Args:
            base_timeout: Initial timeout floor.
            attempt: Retry attempt number (0-indexed).
            request: Model request for adaptive scaling.

        Returns:
            Escalated timeout in seconds, capped at max_seconds.
        """
        # Escalate base timeout on retry (IG-295)
        escalated_base = int(base_timeout * (self._timeout_retry_multiplier**attempt))

        # Apply adaptive scaling on escalated base (IG-301)
        est = estimate_model_request_prompt_chars(request)
        return compute_effective_llm_call_timeout(
            base_seconds=escalated_base,
            max_seconds=self._call_timeout_max,
            prompt_char_estimate=est,
            adaptive=self._call_timeout_adaptive,
        )

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
        """Async wrapper with thread-local rate limiting and retry (Phase 2, IG-295).

        Phase 2 improvements:
        - Thread-local budget isolation (no cross-thread blocking)
        - Per-thread semaphore (no starvation from slow calls)
        - Fair RPM distribution across active threads

        IG-295 improvements:
        - Retry with timeout escalation on TimeoutError
        - Enhanced timeout error with metadata
        - Graceful degradation (RFC-000 Principle #10)

        Args:
            request: Model request with messages and parameters.
            handler: Next handler in middleware chain (actual LLM call).

        Returns:
            Model response from LLM.

        Raises:
            EnhancedTimeoutError: When retries exhausted after timeout.
        """
        # Get thread_id from request context (if available)
        thread_id = getattr(request, "thread_id", "default")

        # Determine max attempts (retry + initial attempt)
        max_attempts = self._max_timeout_retries + 1 if self._retry_on_timeout else 1

        if self._thread_local_enabled:
            # Phase 2: Thread-local rate limiting
            budget = await self._get_thread_budget(thread_id)

            # Use thread-local semaphore (no cross-thread contention)
            async with budget.semaphore:
                # Thread-local RPM check (only blocks this thread)
                await budget.wait_for_rpm_slot()

                # Retry loop with timeout escalation (IG-295)
                for attempt in range(max_attempts):
                    # Calculate timeout (escalate on retry, IG-295)
                    eff_timeout = self._calculate_retry_timeout(
                        base_timeout=self._call_timeout,
                        attempt=attempt,
                        request=request,
                    )

                    try:
                        response = await asyncio.wait_for(handler(request), timeout=eff_timeout)
                        budget.record_request()
                        return response
                    except TimeoutError:
                        if attempt < max_attempts - 1:
                            # Retry with increased timeout
                            logger.warning(
                                "LLM call timeout (attempt %d/%d, %ds) - retrying with increased timeout (thread_id=%s)",
                                attempt + 1,
                                max_attempts,
                                eff_timeout,
                                thread_id,
                            )
                            # Brief backoff before retry
                            await asyncio.sleep(1.0 * attempt)
                        else:
                            # Final attempt failed - emit enhanced timeout error (IG-295)
                            logger.error(
                                "LLM call exceeded timeout after %d retries (%ds final timeout, thread_id=%s)",
                                max_attempts,
                                eff_timeout,
                                thread_id,
                            )
                            # Raise enhanced TimeoutError with metadata
                            raise EnhancedTimeoutError(
                                timeout_seconds=eff_timeout,
                                retries=max_attempts - 1,
                                prompt_chars=estimate_model_request_prompt_chars(request),
                                thread_id=thread_id,
                            )
        else:
            # Legacy global mode (fallback)
            async with self._semaphore:
                await self._enforce_rpm_limit_global()

                # Retry loop with timeout escalation (IG-295)
                for attempt in range(max_attempts):
                    eff_timeout = self._calculate_retry_timeout(
                        base_timeout=self._call_timeout,
                        attempt=attempt,
                        request=request,
                    )

                    try:
                        response = await asyncio.wait_for(handler(request), timeout=eff_timeout)
                        await self._record_request_time_global()
                        return response
                    except TimeoutError:
                        if attempt < max_attempts - 1:
                            logger.warning(
                                "LLM call timeout (attempt %d/%d, %ds) - retrying",
                                attempt + 1,
                                max_attempts,
                                eff_timeout,
                            )
                            await asyncio.sleep(1.0 * attempt)
                        else:
                            logger.error(
                                "LLM call exceeded timeout after %d retries (%ds final timeout)",
                                max_attempts,
                                eff_timeout,
                            )
                            raise EnhancedTimeoutError(
                                timeout_seconds=eff_timeout,
                                retries=max_attempts - 1,
                                prompt_chars=estimate_model_request_prompt_chars(request),
                                thread_id=thread_id,
                            )

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
