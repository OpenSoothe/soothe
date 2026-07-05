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
from typing import Any, TypeVar

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse

from soothe.utils.token_counting import estimate_content_chars

logger = logging.getLogger(__name__)

T = TypeVar("T")


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


def resolve_llm_budget_key(thread_id: str | None) -> str:
    """Resolve the shared RPM budget key for middleware and direct LLM paths."""
    if thread_id:
        return thread_id
    try:
        from soothe.logging.context import get_thread_id

        ctx = get_thread_id()
        if ctx:
            return ctx
    except ImportError:
        pass
    return "direct"


def effective_llm_call_timeout(
    config: Any,
    *,
    timeout_attempts: int,
    rate_limit_attempts: int,
) -> int:
    """Compute per-attempt timeout; 429 retries use a shorter cap."""
    from soothe.config.models import LLMRateLimitConfig

    if not isinstance(config, LLMRateLimitConfig):
        return int(getattr(config, "call_timeout_seconds", 600))
    if rate_limit_attempts > 0:
        return config.rate_limit_retry_timeout_seconds
    escalated = int(
        config.call_timeout_seconds * (config.timeout_retry_multiplier**timeout_attempts)
    )
    return min(escalated, config.call_timeout_max_seconds)


def calc_rate_limit_backoff(
    attempt: int,
    exc: Exception | None,
    *,
    base: float,
    backoff_max: float,
    respect_retry_after: bool,
) -> float:
    """Exponential backoff for 429 retries, honoring retry-after when configured."""
    if respect_retry_after and exc is not None:
        retry_after = _extract_retry_after_seconds(exc)
        if retry_after is not None:
            return min(retry_after, backoff_max)
    return min(base * (2**attempt), backoff_max)


def _emit_llm_retry_event(
    *,
    attempt: int,
    max_attempts: int,
    error_type: str,
    thread_id: str | None,
    log: logging.Logger,
) -> None:
    """Emit retry attempt event for TUI step status display."""
    try:
        from soothe.foundation.events.catalog import LLMRetryAttemptEvent
        from soothe.utils.progress import emit_progress

        event = LLMRetryAttemptEvent(
            attempt=attempt,
            max_attempts=max_attempts,
            error_type=error_type,
            thread_id=thread_id,
        )
        emit_progress(event.to_dict(), log)
    except Exception:
        log.debug("Failed to emit LLM retry event", exc_info=True)


class LLMRateLimitRegistry:
    """Process-wide RPM/concurrency coordinator for middleware and direct LLM calls."""

    _shared: LLMRateLimitRegistry | None = None

    def __init__(self) -> None:
        self._rpm_limit_global = 60
        self._concurrent_limit_per_thread = 8
        self._thread_budgets: dict[str, ThreadBudget] = {}
        self._budget_lock = asyncio.Lock()

    @classmethod
    def shared(cls) -> LLMRateLimitRegistry:
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    @classmethod
    def reset_for_tests(cls) -> None:
        """Clear singleton state between tests."""
        cls._shared = None

    @property
    def thread_budgets(self) -> dict[str, ThreadBudget]:
        return self._thread_budgets

    @property
    def rpm_limit_global(self) -> int:
        return self._rpm_limit_global

    def update_limits(self, *, requests_per_minute: int, concurrent_limit_per_thread: int) -> None:
        """Refresh global limits when middleware is constructed."""
        self._rpm_limit_global = requests_per_minute
        self._concurrent_limit_per_thread = concurrent_limit_per_thread

    async def get_budget(self, thread_id: str) -> ThreadBudget:
        """Get or create a fair-share RPM budget for ``thread_id``."""
        async with self._budget_lock:
            if thread_id not in self._thread_budgets:
                active_threads = len(self._thread_budgets)
                thread_rpm = max(self._rpm_limit_global // (active_threads + 1), 10)
                self._thread_budgets[thread_id] = ThreadBudget(
                    rpm_limit=thread_rpm,
                    semaphore_max=self._concurrent_limit_per_thread,
                )
                logger.debug(
                    "Thread budget created: thread_id=%s rpm=%d/%d active_threads=%d",
                    thread_id,
                    thread_rpm,
                    self._rpm_limit_global,
                    active_threads + 1,
                )
            return self._thread_budgets[thread_id]

    async def redistribute_budgets(self) -> None:
        async with self._budget_lock:
            active_threads = len(self._thread_budgets)
            if active_threads <= 0:
                return
            thread_rpm = max(self._rpm_limit_global // active_threads, 10)
            for budget in self._thread_budgets.values():
                budget.rpm_limit = thread_rpm
            logger.info(
                "Budgets redistributed: rpm_per_thread=%d active_threads=%d",
                thread_rpm,
                active_threads,
            )

    def cleanup_thread_budget(self, thread_id: str) -> None:
        if thread_id in self._thread_budgets:
            del self._thread_budgets[thread_id]
            logger.info("Thread budget removed: thread_id=%s", thread_id)
            asyncio.create_task(self.redistribute_budgets())

    def adjust_rpm_limit(self, new_limit: int, reason: str) -> None:
        new_limit = max(5, min(new_limit, 10_000))
        old_limit = self._rpm_limit_global
        if new_limit == old_limit:
            return
        self._rpm_limit_global = new_limit
        logger.warning(
            "RPM limit adjusted: %d → %d (reason: %s) active_threads=%d",
            old_limit,
            new_limit,
            reason,
            len(self._thread_budgets),
        )
        asyncio.create_task(self.redistribute_budgets())


async def run_llm_call_with_policy(
    call: Callable[[], Awaitable[T]],
    *,
    config: Any,
    budget_key: str,
    thread_id: str | None = None,
    prompt_chars: int = 0,
    log_prefix: str = "LLM",
    log: logging.Logger | None = None,
) -> T:
    """Run an LLM call with shared RPM limits, timeouts, and 429/timeout retry."""
    from soothe.config.models import LLMRateLimitConfig

    if not isinstance(config, LLMRateLimitConfig):
        msg = "run_llm_call_with_policy requires LLMRateLimitConfig"
        raise TypeError(msg)

    call_log = log or logger
    registry = LLMRateLimitRegistry.shared()
    budget = await registry.get_budget(budget_key)
    telemetry_id = thread_id or budget_key

    timeout_attempts = 0
    rate_limit_attempts = 0
    max_timeout_attempts = config.max_timeout_retries + 1 if config.retry_on_timeout else 1
    max_rate_limit_attempts = config.max_rate_limit_retries + 1 if config.retry_on_rate_limit else 1

    while True:
        eff_timeout = effective_llm_call_timeout(
            config,
            timeout_attempts=timeout_attempts,
            rate_limit_attempts=rate_limit_attempts,
        )
        call_log.debug(
            "%s call starting (timeout=%ds timeout_try=%d/%d rate_limit_try=%d/%d "
            "budget_key=%s thread_id=%s)",
            log_prefix,
            eff_timeout,
            timeout_attempts + 1,
            max_timeout_attempts,
            rate_limit_attempts + 1,
            max_rate_limit_attempts,
            budget_key,
            telemetry_id,
        )

        retry_sleep: float | None = None
        retry_error_type: str | None = None
        retry_attempt = 0
        retry_max = 0

        async with budget.semaphore:
            await budget.wait_for_rpm_slot()
            try:
                result = await asyncio.wait_for(call(), timeout=eff_timeout)
                budget.record_request()
                return result

            except TimeoutError:
                timeout_attempts += 1
                if timeout_attempts >= 2:
                    proactive_limit = int(registry.rpm_limit_global * 0.8)
                    registry.adjust_rpm_limit(
                        proactive_limit,
                        reason=(
                            f"consecutive timeouts ({timeout_attempts}) suggesting provider overload"
                        ),
                    )
                if timeout_attempts < max_timeout_attempts:
                    retry_sleep = 1.0 * timeout_attempts
                    retry_error_type = "timeout"
                    retry_attempt = timeout_attempts
                    retry_max = max_timeout_attempts
                else:
                    call_log.error(
                        "%s exceeded timeout after %d attempts (%ds final, thread_id=%s)",
                        log_prefix,
                        max_timeout_attempts,
                        eff_timeout,
                        telemetry_id,
                    )
                    raise EnhancedTimeoutError(
                        timeout_seconds=eff_timeout,
                        retries=max_timeout_attempts - 1,
                        prompt_chars=prompt_chars,
                        thread_id=telemetry_id or budget_key,
                    ) from None

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                if _is_api_rate_limit_error(exc):
                    rate_limit_info = _extract_rate_limit_info(exc)
                    call_log.warning(
                        "%s rate limited: retry_after=%ss rpm_hint=%s provider=%s (thread_id=%s)",
                        log_prefix,
                        rate_limit_info["retry_after_seconds"] or "none",
                        rate_limit_info["rpm_limit_hint"] or "none",
                        rate_limit_info["provider_name"] or "unknown",
                        telemetry_id,
                    )
                    if rate_limit_info["rpm_limit_hint"] is not None:
                        registry.adjust_rpm_limit(
                            rate_limit_info["rpm_limit_hint"],
                            reason=f"429 from {rate_limit_info['provider_name'] or 'provider'}",
                        )
                    rate_limit_attempts += 1
                    if rate_limit_attempts < max_rate_limit_attempts:
                        retry_sleep = calc_rate_limit_backoff(
                            rate_limit_attempts - 1,
                            exc,
                            base=config.rate_limit_backoff_base,
                            backoff_max=config.rate_limit_backoff_max,
                            respect_retry_after=config.respect_retry_after_header,
                        )
                        retry_error_type = "rate_limit"
                        retry_attempt = rate_limit_attempts
                        retry_max = max_rate_limit_attempts
                    else:
                        call_log.error(
                            "%s rate limited (429) after %d retries (thread_id=%s)",
                            log_prefix,
                            max_rate_limit_attempts,
                            telemetry_id,
                        )
                        raise

                elif _is_transient_connection_error(exc):
                    connection_attempts = 0
                    max_connection_attempts = 3
                    while connection_attempts < max_connection_attempts:
                        connection_attempts += 1
                        conn_backoff = 2.0 * connection_attempts
                        call_log.warning(
                            "%s connection error (attempt %d/%d) - retrying in %.1fs "
                            "(thread_id=%s): %s",
                            log_prefix,
                            connection_attempts,
                            max_connection_attempts,
                            conn_backoff,
                            telemetry_id,
                            str(exc)[:100],
                        )
                        await asyncio.sleep(conn_backoff)
                        try:
                            result = await asyncio.wait_for(call(), timeout=eff_timeout)
                            budget.record_request()
                            return result
                        except Exception as retry_exc:
                            if not _is_transient_connection_error(retry_exc):
                                raise
                            exc = retry_exc
                            continue
                    call_log.error(
                        "%s connection error after %d retries (thread_id=%s): %s",
                        log_prefix,
                        max_connection_attempts,
                        telemetry_id,
                        str(exc)[:100],
                    )
                    raise

                else:
                    raise

        if retry_sleep is not None and retry_error_type is not None:
            retry_label = "timeout" if retry_error_type == "timeout" else "429"
            call_log.warning(
                "%s %s (attempt %d/%d) - retrying in %.1fs (thread_id=%s)",
                log_prefix,
                retry_label,
                retry_attempt,
                retry_max,
                retry_sleep,
                telemetry_id,
            )
            _emit_llm_retry_event(
                attempt=retry_attempt,
                max_attempts=retry_max,
                error_type=retry_error_type,
                thread_id=telemetry_id,
                log=call_log,
            )
            await asyncio.sleep(retry_sleep)
            continue


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
        rate_limit_retry_timeout_seconds: int = 120,
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
            rate_limit_retry_timeout_seconds: Shorter timeout for post-429 retries (default 120s).
        """
        super().__init__()
        from soothe.config.models import LLMRateLimitConfig

        self._concurrent_limit_per_thread = max_concurrent_requests_per_thread
        self._policy_config = LLMRateLimitConfig(
            enabled=True,
            rpm_limit=requests_per_minute,
            concurrent_limit=max_concurrent_requests_per_thread,
            call_timeout_seconds=call_timeout_seconds,
            call_timeout_max_seconds=max(call_timeout_max_seconds, call_timeout_seconds),
            retry_on_timeout=retry_on_timeout,
            max_timeout_retries=max_timeout_retries,
            timeout_retry_multiplier=timeout_retry_multiplier,
            retry_on_rate_limit=retry_on_rate_limit,
            max_rate_limit_retries=max_rate_limit_retries,
            rate_limit_backoff_base=rate_limit_backoff_base,
            rate_limit_backoff_max=rate_limit_backoff_max,
            respect_retry_after_header=respect_retry_after_header,
            rate_limit_retry_timeout_seconds=rate_limit_retry_timeout_seconds,
        )
        LLMRateLimitRegistry.shared().update_limits(
            requests_per_minute=requests_per_minute,
            concurrent_limit_per_thread=max_concurrent_requests_per_thread,
        )

        logger.info(
            "LLM rate limiter initialized (thread-local): global_rpm=%d, "
            "per_thread_concurrent=%d, timeout=%ds timeout_cap=%ds "
            "retry_timeout=%s max_timeout_retries=%d retry_multiplier=%.1f "
            "retry_429=%s max_429_retries=%d backoff_base=%.1fs backoff_max=%.1fs "
            "retry_after_header=%s rate_limit_retry_timeout=%ds",
            requests_per_minute,
            max_concurrent_requests_per_thread,
            call_timeout_seconds,
            self._policy_config.call_timeout_max_seconds,
            retry_on_timeout,
            max_timeout_retries,
            timeout_retry_multiplier,
            retry_on_rate_limit,
            max_rate_limit_retries,
            rate_limit_backoff_base,
            rate_limit_backoff_max,
            respect_retry_after_header,
            rate_limit_retry_timeout_seconds,
        )

    @property
    def _thread_budgets(self) -> dict[str, ThreadBudget]:
        return LLMRateLimitRegistry.shared().thread_budgets

    @property
    def _rpm_limit_global(self) -> int:
        return LLMRateLimitRegistry.shared().rpm_limit_global

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
        """IG-504: Emit retry attempt event for TUI step status display."""
        _emit_llm_retry_event(
            attempt=attempt,
            max_attempts=max_attempts,
            error_type=error_type,
            thread_id=thread_id,
            log=logger,
        )

    async def _get_thread_budget(self, thread_id: str) -> ThreadBudget:
        return await LLMRateLimitRegistry.shared().get_budget(thread_id)

    def cleanup_thread_budget(self, thread_id: str) -> None:
        LLMRateLimitRegistry.shared().cleanup_thread_budget(thread_id)

    def adjust_rpm_limit(self, new_limit: int, reason: str) -> None:
        LLMRateLimitRegistry.shared().adjust_rpm_limit(new_limit, reason)

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        """Synchronous wrapper (not used for async LLM calls)."""
        logger.warning("Unexpected synchronous LLM call in async middleware")
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Async wrapper delegating to the shared LLM retry runner."""
        budget_key = self._thread_id_from_request(request)

        async def _invoke() -> ModelResponse[Any]:
            return await handler(request)

        return await run_llm_call_with_policy(
            _invoke,
            config=self._policy_config,
            budget_key=budget_key,
            thread_id=budget_key,
            prompt_chars=estimate_model_request_prompt_chars(request),
            log_prefix="LLM call",
            log=logger,
        )

    def get_stats(self) -> dict[str, Any]:
        """Get rate limiting statistics."""
        registry = LLMRateLimitRegistry.shared()
        thread_stats = {
            thread_id: budget.get_stats() for thread_id, budget in registry.thread_budgets.items()
        }
        return {
            "mode": "thread_local",
            "global_rpm_limit": registry.rpm_limit_global,
            "per_thread_concurrent_limit": self._concurrent_limit_per_thread,
            "active_threads": len(registry.thread_budgets),
            "thread_budgets": thread_stats,
        }
