"""Rate limiting middleware for LLM API calls.

This middleware throttles LLM API calls at the model level, not thread level,
allowing multiple threads to run concurrently while limiting actual API request rate.

IG-258 Phase 2: Thread-local rate limiting to prevent cross-thread contention.
IG-499: HTTP 429 rate limit error retry with exponential backoff.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse

from soothe.utils.token_counting import estimate_content_chars

logger = logging.getLogger(__name__)


# IG-499: Helper functions for 429 error detection and retry-after extraction


def _iter_exception_chain(exc: BaseException) -> list[BaseException]:
    """Walk ``__cause__`` / ``__context__`` without cycles."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _is_api_rate_limit_error(exc: Exception) -> bool:
    """Check if exception is a 429 rate limit error from OpenAI/Anthropic APIs.

    Detection strategy:
    1. Check class name (OpenAI/Anthropic RateLimitError)
    2. Check response.status_code attribute
    3. Fallback: keyword matching in error string

    Walks the exception chain so wrapped errors (e.g. ``StructuredOutputError``)
    still trigger retry when the underlying provider raised 429.

    Args:
        exc: Exception to check.

    Returns:
        True if this is a 429 rate limit error that should trigger retry.
    """
    for link in _iter_exception_chain(exc):
        exc_type_name = type(link).__name__
        if exc_type_name == "RateLimitError":
            return True

        response = getattr(link, "response", None)
        if response is not None:
            status_code = getattr(response, "status_code", None)
            if status_code == 429:
                return True

        error_str = str(link).lower()
        if "429" in error_str or "rate limit" in error_str or "throttling" in error_str:
            return True

    return False


# IG-503: Helper function for transient connection error detection


def _is_transient_connection_error(exc: Exception) -> bool:
    """Check if exception is a transient connection/network error that warrants retry.

    Covers connection errors, timeouts, and SSL/TLS errors from various providers
    (httpx, OpenAI SDK, Anthropic SDK, aiohttp, etc.).

    Args:
        exc: Exception to check.

    Returns:
        True if this is a transient connection error that should be retried.
    """
    # Check by exception class name
    exc_type_name = type(exc).__name__
    transient_types = {
        "ConnectionError",
        "ConnectError",
        "NetworkError",
        "ReadTimeout",
        "WriteTimeout",
        "ConnectTimeout",
        "RemoteProtocolError",
        "LocalProtocolError",
        "StreamError",
    }
    if exc_type_name in transient_types:
        return True

    # Check module name for httpx exceptions
    exc_module = str(type(exc).__module__)
    if "httpx" in exc_module:
        if exc_type_name in (
            "ConnectError",
            "ReadTimeout",
            "WriteTimeout",
            "ConnectTimeout",
            "StreamConsumed",
            "RemoteProtocolError",
        ):
            return True

    # Check for aiohttp exceptions
    if "aiohttp" in exc_module:
        if exc_type_name in (
            "ClientConnectionError",
            "ClientConnectorError",
            "ClientOSError",
            "ClientPayloadError",
            "ClientResponseError",
            "ServerTimeoutError",
            "ClientTimeout",
        ):
            return True

    # Fallback: keyword matching in error string
    error_str = str(exc).lower()
    transient_keywords = [
        "connection error",
        "connection refused",
        "connection reset",
        "connection closed",
        "network unreachable",
        "network error",
        "timeout",
        "timed out",
        "socket error",
        "ssl error",
        "tls error",
        "certificate error",
        "eof occurred in violation of protocol",
        "protocol error",
        "stream error",
        "temporary failure",
    ]
    return any(kw in error_str for kw in transient_keywords)


def _extract_retry_after_seconds(exc: Exception) -> float | None:
    """Extract retry-after header value from API error response.

    OpenAI and Anthropic often include a 'retry-after' header in 429 responses
    indicating when the client should retry. Using this value is more efficient
    than exponential backoff.

    Args:
        exc: Exception with response attribute containing headers.

    Returns:
        Retry-after value in seconds, or None if not present/parseable.
    """
    for link in _iter_exception_chain(exc):
        response = getattr(link, "response", None)
        if response is None:
            continue

        headers = getattr(response, "headers", None)
        if headers is None:
            continue

        retry_after = headers.get("retry-after")
        if retry_after is None:
            continue

        try:
            return float(retry_after)
        except ValueError:
            continue

    return None


# IG-501: Extended rate limit info extraction for Chinese providers


def _extract_rate_limit_info(exc: Exception) -> dict[str, Any]:
    """Extract rate limit info from provider error response.

    Dashscope/Zhipu use OpenAI-compatible format:
    - HTTP 429 status
    - JSON body with error details
    - May include retry_after or wait_seconds in body
    - May communicate actual RPM limit

    Args:
        exc: Exception with response attribute.

    Returns:
        dict with:
            - retry_after_seconds: float | None
            - rpm_limit_hint: int | None (if provider specifies actual limit)
            - provider_name: str | None (dashscope/zhipu/etc)
    """
    result: dict[str, Any] = {
        "retry_after_seconds": None,
        "rpm_limit_hint": None,
        "provider_name": None,
    }

    response = None
    for link in _iter_exception_chain(exc):
        response = getattr(link, "response", None)
        if response is not None:
            break
    if response is None:
        return result

    # 1. Standard retry-after header
    headers = getattr(response, "headers", {})
    if headers:
        retry_after = headers.get("retry-after")
        if retry_after:
            try:
                result["retry_after_seconds"] = float(retry_after)
            except ValueError:
                pass

    # 2. Response body parsing (Dashscope/Zhipu specific)
    try:
        body = response.json()
        error_obj = body.get("error", {})

        # Dashscope/Zhipu may include retry info in body
        # Only use body value if header didn't provide one (header takes priority)
        if result["retry_after_seconds"] is None:
            if "retry_after" in error_obj:
                try:
                    result["retry_after_seconds"] = float(error_obj["retry_after"])
                except (TypeError, ValueError):
                    pass
            elif "wait_seconds" in error_obj:
                try:
                    result["retry_after_seconds"] = float(error_obj["wait_seconds"])
                except (TypeError, ValueError):
                    pass

        # Provider may communicate their actual limit
        rate_limit_obj = error_obj.get("rate_limit", {})
        if rate_limit_obj and "limit" in rate_limit_obj:
            try:
                result["rpm_limit_hint"] = int(rate_limit_obj["limit"])
            except (TypeError, ValueError):
                pass

        # Detect provider from error code/message
        message = error_obj.get("message", "") or str(body)
        message_lower = message.lower()
        if "dashscope" in message_lower or "qwen" in message_lower:
            result["provider_name"] = "dashscope"
        elif "zhipu" in message_lower or "glm" in message_lower:
            result["provider_name"] = "zhipu"
        elif "kimi" in message_lower or "moonshot" in message_lower:
            result["provider_name"] = "kimi"

    except (json.JSONDecodeError, AttributeError, TypeError):
        # Body parsing failed, use header values only
        pass

    return result


def estimate_model_request_prompt_chars(request: ModelRequest[Any]) -> int:
    """Sum system prompt and message text lengths for timeout error metadata."""
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

    IG-499: HTTP 429 retry with exponential backoff and retry-after header support.

    Example:
        ```python
        from soothe.middleware.llm_rate_limit import LLMRateLimitMiddleware

        middleware = LLMRateLimitMiddleware(
            requests_per_minute=120,
            max_concurrent_requests_per_thread=10,
            call_timeout_seconds=600,  # IG-504: Increased timeout
            call_timeout_max_seconds=900,  # IG-504: Increased cap
            retry_on_timeout=True,  # IG-295
            max_timeout_retries=10,  # IG-504: Increased retries
            timeout_retry_multiplier=1.2,  # IG-295
            retry_on_rate_limit=True,  # IG-499
            max_rate_limit_retries=10,  # IG-504: Increased 429 retries
            rate_limit_backoff_base=2.0,  # IG-499
            rate_limit_backoff_max=60.0,  # IG-499
            respect_retry_after_header=True,  # IG-499
        )
        ```

    Args:
        requests_per_minute: Global RPM limit (distributed across threads).
        max_concurrent_requests_per_thread: Max concurrent per thread (Phase 2).
        call_timeout_seconds: Base duration per LLM call before timeout.
        call_timeout_max_seconds: Ceiling for retry timeout escalation (IG-295).
        retry_on_timeout: Enable retry with timeout escalation (IG-295, default True).
        max_timeout_retries: Max retry attempts after timeout (IG-295, default 2).
        timeout_retry_multiplier: Timeout multiplier on retry (IG-295, default 1.2).
        retry_on_rate_limit: Enable retry on HTTP 429 errors (IG-499, default True).
        max_rate_limit_retries: Max retry attempts after 429 (IG-499, default 3).
        rate_limit_backoff_base: Exponential backoff base in seconds (IG-499, default 2.0).
        rate_limit_backoff_max: Maximum backoff wait in seconds (IG-499, default 60.0).
        respect_retry_after_header: Use retry-after header when present (IG-499, default True).
    """

    name = "LLMRateLimitMiddleware"

    def __init__(
        self,
        requests_per_minute: int = 120,
        max_concurrent_requests_per_thread: int = 10,
        call_timeout_seconds: int = 600,  # IG-504: Increased timeout
        call_timeout_max_seconds: int = 900,  # IG-504: Increased cap
        retry_on_timeout: bool = True,  # IG-295
        max_timeout_retries: int = 10,  # IG-504: Increased retries
        timeout_retry_multiplier: float = 1.2,  # IG-295
        retry_on_rate_limit: bool = True,  # IG-499
        max_rate_limit_retries: int = 10,  # IG-504: Increased 429 retries
        rate_limit_backoff_base: float = 2.0,  # IG-499
        rate_limit_backoff_max: float = 60.0,  # IG-499
        respect_retry_after_header: bool = True,  # IG-499
    ) -> None:
        """Initialize rate limiter with thread-local budgets and retry (Phase 2, IG-295, IG-499).

        Args:
            requests_per_minute: Global RPM limit (default: 120).
            max_concurrent_requests_per_thread: Max concurrent per thread (Phase 2, default: 10).
            call_timeout_seconds: Base max duration per LLM call (IG-504: default 600s).
            call_timeout_max_seconds: Retry timeout ceiling (IG-504: default 900s).
            retry_on_timeout: Enable retry with timeout escalation (IG-295, default True).
            max_timeout_retries: Max retry attempts after timeout (IG-504: default 10).
            timeout_retry_multiplier: Timeout multiplier on retry (IG-295, default 1.2).
            retry_on_rate_limit: Enable retry on HTTP 429 errors (IG-499, default True).
            max_rate_limit_retries: Max retry attempts after 429 (IG-504: default 10).
            rate_limit_backoff_base: Exponential backoff base in seconds (IG-499, default 2.0).
            rate_limit_backoff_max: Maximum backoff wait in seconds (IG-499, default 60.0).
            respect_retry_after_header: Use retry-after header when present (IG-499, default True).
        """
        super().__init__()
        self._rpm_limit_global = requests_per_minute
        self._concurrent_limit_per_thread = max_concurrent_requests_per_thread
        self._call_timeout = call_timeout_seconds
        self._call_timeout_max = max(call_timeout_max_seconds, call_timeout_seconds)

        # Retry configuration (IG-295)
        self._retry_on_timeout = retry_on_timeout
        self._max_timeout_retries = max_timeout_retries
        self._timeout_retry_multiplier = timeout_retry_multiplier

        # IG-499: Rate limit retry configuration
        self._retry_on_rate_limit = retry_on_rate_limit
        self._max_rate_limit_retries = max_rate_limit_retries
        self._rate_limit_backoff_base = rate_limit_backoff_base
        self._rate_limit_backoff_max = rate_limit_backoff_max
        self._respect_retry_after_header = respect_retry_after_header

        # Thread-local budgets (Phase 2)
        self._thread_budgets: dict[str, ThreadBudget] = {}
        self._budget_lock = asyncio.Lock()  # Only for budget allocation

        logger.info(
            "LLM rate limiter initialized (thread-local): global_rpm=%d, "
            "per_thread_concurrent=%d, timeout=%ds timeout_cap=%ds "
            "retry_timeout=%s max_timeout_retries=%d retry_multiplier=%.1f "
            "retry_429=%s max_429_retries=%d backoff_base=%.1fs backoff_max=%.1fs retry_after_header=%s",
            requests_per_minute,
            max_concurrent_requests_per_thread,
            call_timeout_seconds,
            self._call_timeout_max,
            retry_on_timeout,
            max_timeout_retries,
            timeout_retry_multiplier,
            retry_on_rate_limit,
            max_rate_limit_retries,
            rate_limit_backoff_base,
            rate_limit_backoff_max,
            respect_retry_after_header,
        )

    @staticmethod
    def _thread_id_from_request(request: ModelRequest[Any]) -> str:
        """Resolve LangGraph ``configurable.thread_id`` for per-stream LLM budgets."""
        runtime = getattr(request, "runtime", None)
        config = getattr(runtime, "config", None) if runtime is not None else None
        if isinstance(config, dict):
            configurable = config.get("configurable", {})
            if isinstance(configurable, dict):
                thread_id = configurable.get("thread_id")
                if isinstance(thread_id, str) and thread_id:
                    return thread_id
        return "default"

    @staticmethod
    def _emit_retry_event(
        attempt: int,
        max_attempts: int,
        error_type: str,
        thread_id: str | None,
        logger: logging.Logger,
    ) -> None:
        """IG-504: Emit retry attempt event for TUI step status display.

        Args:
            attempt: Current attempt number (1-indexed after failure).
            max_attempts: Maximum attempts allowed.
            error_type: "timeout" or "rate_limit".
            thread_id: Thread ID for context.
            logger: Logger for fallback if emit fails.
        """
        try:
            from soothe.foundation.events.catalog import LLMRetryAttemptEvent
            from soothe.utils.progress import emit_progress

            event = LLMRetryAttemptEvent(
                attempt=attempt,
                max_attempts=max_attempts,
                error_type=error_type,
                thread_id=thread_id,
            )
            emit_progress(event.to_dict(), logger)
        except Exception:
            logger.debug("Failed to emit LLM retry event", exc_info=True)

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

    def _calculate_retry_timeout(
        self,
        base_timeout: int,
        attempt: int,
    ) -> int:
        """Calculate timeout with escalation on retry (IG-295).

        Args:
            base_timeout: Initial timeout base.
            attempt: Retry attempt number (0-indexed).

        Returns:
            Escalated timeout in seconds, capped at max_seconds.
        """
        escalated = int(base_timeout * (self._timeout_retry_multiplier**attempt))
        return min(escalated, self._call_timeout_max)

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

    # IG-501: Runtime RPM adjustment based on provider feedback

    def adjust_rpm_limit(self, new_limit: int, reason: str) -> None:
        """Dynamically adjust global RPM limit based on provider feedback.

        Logs the change, validates bounds, and redistributes budgets across
        active threads immediately.

        Args:
            new_limit: New RPM limit to apply (validated: min 5, max 10000).
            reason: Reason for adjustment (e.g., "429 from dashscope").

        Note:
            This is a runtime adjustment only; does not modify config files.
        """
        # Validate bounds
        new_limit = max(5, min(new_limit, 10000))

        old_limit = self._rpm_limit_global
        if new_limit == old_limit:
            return  # No change needed

        self._rpm_limit_global = new_limit

        # Log the adjustment
        active_threads = len(self._thread_budgets)
        logger.warning(
            "RPM limit adjusted: %d → %d (reason: %s) active_threads=%d",
            old_limit,
            new_limit,
            reason,
            active_threads,
        )

        # Redistribute to thread budgets
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

    def _calculate_rate_limit_backoff(self, attempt: int, exc: Exception | None = None) -> float:
        """Calculate backoff delay for 429 rate limit retry (IG-499).

        Prefers retry-after header from API when available and enabled.
        Falls back to exponential backoff: base * 2^attempt.

        Args:
            attempt: Retry attempt number (0-indexed).
            exc: Exception containing response with retry-after header (optional).

        Returns:
            Backoff delay in seconds, capped at backoff_max.
        """
        # Prefer retry-after header if available and enabled
        if self._respect_retry_after_header and exc is not None:
            retry_after = _extract_retry_after_seconds(exc)
            if retry_after is not None:
                return min(retry_after, self._rate_limit_backoff_max)

        # Exponential backoff: base * 2^attempt
        backoff = self._rate_limit_backoff_base * (2**attempt)
        return min(backoff, self._rate_limit_backoff_max)

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Async wrapper with thread-local rate limiting and retry (Phase 2, IG-295, IG-499).

        Phase 2 improvements:
        - Thread-local budget isolation (no cross-thread blocking)
        - Per-thread semaphore (no starvation from slow calls)
        - Fair RPM distribution across active threads

        IG-295 improvements:
        - Retry with timeout escalation on TimeoutError
        - Enhanced timeout error with metadata
        - Graceful degradation (RFC-000 Principle #10)

        IG-499 improvements:
        - Retry on HTTP 429 rate limit errors with exponential backoff
        - Respect retry-after header from API when present
        - Separate retry counters for timeout vs rate limit errors

        Args:
            request: Model request with messages and parameters.
            handler: Next handler in middleware chain (actual LLM call).

        Returns:
            Model response from LLM.

        Raises:
            EnhancedTimeoutError: When timeout retries exhausted.
            Exception: Original 429 error when rate limit retries exhausted.
        """
        thread_id = self._thread_id_from_request(request)

        # IG-499: Separate retry counters for different error types
        timeout_attempts = 0
        rate_limit_attempts = 0
        max_timeout_attempts = self._max_timeout_retries + 1 if self._retry_on_timeout else 1
        max_rate_limit_attempts = (
            self._max_rate_limit_retries + 1 if self._retry_on_rate_limit else 1
        )

        # Phase 2: Thread-local rate limiting
        budget = await self._get_thread_budget(thread_id)

        # Use thread-local semaphore (no cross-thread contention)
        async with budget.semaphore:
            # Thread-local RPM check (only blocks this thread)
            await budget.wait_for_rpm_slot()

            # IG-499: Combined retry loop handling both timeout and 429 errors
            while True:
                # Calculate timeout with escalation based on timeout attempts
                eff_timeout = self._calculate_retry_timeout(
                    base_timeout=self._call_timeout,
                    attempt=timeout_attempts,
                )

                try:
                    response = await asyncio.wait_for(handler(request), timeout=eff_timeout)
                    budget.record_request()
                    return response

                except TimeoutError:
                    # IG-295: Timeout retry handling
                    timeout_attempts += 1

                    # IG-501: Proactive throttling after consecutive timeouts
                    # (suggests provider overload, reduce RPM before hitting 429)
                    if timeout_attempts >= 2:
                        proactive_limit = int(self._rpm_limit_global * 0.8)  # Reduce by 20%
                        self.adjust_rpm_limit(
                            proactive_limit,
                            reason=f"consecutive timeouts ({timeout_attempts}) suggesting provider overload",
                        )

                    if timeout_attempts < max_timeout_attempts:
                        backoff = 1.0 * timeout_attempts
                        logger.debug(
                            "LLM call timeout (attempt %d/%d, %ds) - retrying with backoff=%.1fs (thread_id=%s)",
                            timeout_attempts,
                            max_timeout_attempts,
                            eff_timeout,
                            backoff,
                            thread_id,
                        )
                        # IG-504: Emit retry event for TUI display
                        self._emit_retry_event(
                            attempt=timeout_attempts,
                            max_attempts=max_timeout_attempts,
                            error_type="timeout",
                            thread_id=thread_id,
                            logger=logger,
                        )
                        await asyncio.sleep(backoff)
                        continue
                    else:
                        # Final timeout attempt failed
                        logger.error(
                            "LLM call exceeded timeout after %d retries (%ds final timeout, thread_id=%s)",
                            max_timeout_attempts,
                            eff_timeout,
                            thread_id,
                        )
                        raise EnhancedTimeoutError(
                            timeout_seconds=eff_timeout,
                            retries=max_timeout_attempts - 1,
                            prompt_chars=estimate_model_request_prompt_chars(request),
                            thread_id=thread_id,
                        )

                except Exception as exc:
                    # IG-499: Check for 429 rate limit error
                    if _is_api_rate_limit_error(exc):
                        # IG-501: Extract full rate limit info from provider response
                        rate_limit_info = _extract_rate_limit_info(exc)

                        # Log detection
                        logger.warning(
                            "Rate limit detected: retry_after=%ss rpm_hint=%s provider=%s (thread_id=%s)",
                            rate_limit_info["retry_after_seconds"] or "none",
                            rate_limit_info["rpm_limit_hint"] or "none",
                            rate_limit_info["provider_name"] or "unknown",
                            thread_id,
                        )

                        # IG-501: Adjust global RPM if provider gave us a hint
                        if rate_limit_info["rpm_limit_hint"] is not None:
                            self.adjust_rpm_limit(
                                rate_limit_info["rpm_limit_hint"],
                                reason=f"429 from {rate_limit_info['provider_name'] or 'provider'}",
                            )

                        if rate_limit_attempts < max_rate_limit_attempts - 1:
                            rate_limit_attempts += 1
                            backoff = self._calculate_rate_limit_backoff(
                                attempt=rate_limit_attempts - 1,
                                exc=exc,
                            )
                            logger.warning(
                                "LLM call rate limited (429) (attempt %d/%d) - retrying with backoff=%.1fs (thread_id=%s)",
                                rate_limit_attempts,
                                max_rate_limit_attempts,
                                backoff,
                                thread_id,
                            )
                            # IG-504: Emit retry event for TUI display
                            self._emit_retry_event(
                                attempt=rate_limit_attempts,
                                max_attempts=max_rate_limit_attempts,
                                error_type="rate_limit",
                                thread_id=thread_id,
                                logger=logger,
                            )
                            await asyncio.sleep(backoff)
                            continue
                        else:
                            # Final rate limit attempt failed
                            logger.error(
                                "LLM call rate limited (429) after %d retries (thread_id=%s)",
                                max_rate_limit_attempts,
                                thread_id,
                            )
                            raise

                    # IG-503: Check for transient connection error
                    elif _is_transient_connection_error(exc):
                        connection_attempts = 0
                        max_connection_attempts = 3
                        while connection_attempts < max_connection_attempts:
                            connection_attempts += 1
                            backoff = 2.0 * connection_attempts  # Linear backoff: 2s, 4s, 6s
                            logger.warning(
                                "LLM connection error (attempt %d/%d) - retrying with backoff=%.1fs (thread_id=%s): %s",
                                connection_attempts,
                                max_connection_attempts,
                                backoff,
                                thread_id,
                                str(exc)[:100],
                            )
                            await asyncio.sleep(backoff)
                            try:
                                response = await asyncio.wait_for(
                                    handler(request), timeout=eff_timeout
                                )
                                budget.record_request()
                                return response
                            except Exception as retry_exc:
                                if not _is_transient_connection_error(retry_exc):
                                    raise  # Non-transient, propagate
                                exc = retry_exc
                                continue

                        # All connection retries exhausted
                        logger.error(
                            "LLM connection error after %d retries (thread_id=%s): %s",
                            max_connection_attempts,
                            thread_id,
                            str(exc)[:100],
                        )
                        raise

                    else:
                        # Non-rate-limit, non-timeout, non-connection error: propagate immediately
                        raise

    def get_stats(self) -> dict[str, Any]:
        """Get rate limiting statistics.

        Returns:
            Dictionary with thread-local statistics.
        """
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
