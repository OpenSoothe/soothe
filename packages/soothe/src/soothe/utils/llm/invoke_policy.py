"""Bounded async LLM invocation with timeout and retry (planner / structured paths).

CoreAgent model calls use ``LLMRateLimitMiddleware`` on the middleware stack.
Planner and other direct ``ainvoke`` / structured-output paths bypass that stack;
this module applies the same per-call timeout and retry policy from
``LLMRateLimitConfig``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from soothe.config.models import LLMRateLimitConfig
from soothe.middleware.llm_rate_limit import (
    EnhancedTimeoutError,
    _extract_rate_limit_info,
    _is_api_rate_limit_error,
    _is_transient_connection_error,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


def llm_rate_limit_config_from(soothe_config: Any | None) -> LLMRateLimitConfig:
    """Resolve direct-call timeout/retry policy from ``SootheConfig``."""
    if soothe_config is not None:
        agent = getattr(soothe_config, "agent", None)
        loop = getattr(agent, "loop", None) if agent is not None else None
        llm_rate_limit = getattr(loop, "llm_rate_limit", None) if loop is not None else None
        if isinstance(llm_rate_limit, LLMRateLimitConfig):
            return llm_rate_limit
    return LLMRateLimitConfig()


def run_with_llm_call_policy_sync(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    config: LLMRateLimitConfig,
    thread_id: str | None = None,
) -> T:
    """Run ``await_with_llm_call_policy`` from a sync caller without a running loop."""

    async def _run() -> T:
        return await await_with_llm_call_policy(
            coro_factory,
            config=config,
            thread_id=thread_id,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run())

    msg = "run_with_llm_call_policy_sync cannot be called from a running event loop"
    raise RuntimeError(msg)


def _calc_retry_timeout(base: int, attempt: int, *, cap: int, multiplier: float) -> int:
    escalated = int(base * (multiplier**attempt))
    return min(escalated, cap)


def _emit_retry_event(
    *,
    attempt: int,
    max_attempts: int,
    error_type: str,
    thread_id: str | None,
) -> None:
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


def _calc_rate_limit_backoff(
    attempt: int,
    exc: Exception | None,
    *,
    base: float,
    backoff_max: float,
    respect_retry_after: bool,
) -> float:
    if respect_retry_after and exc is not None:
        from soothe.middleware.llm_rate_limit import _extract_retry_after_seconds

        retry_after = _extract_retry_after_seconds(exc)
        if retry_after is not None:
            return min(retry_after, backoff_max)
    return min(base * (2**attempt), backoff_max)


async def await_with_llm_call_policy(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    config: LLMRateLimitConfig,
    thread_id: str | None = None,
) -> T:
    """Run ``coro_factory`` with per-call timeout and retry policy.

    Mirrors the timeout / 429 / connection-retry behavior of
    ``LLMRateLimitMiddleware.awrap_model_call`` without RPM or semaphore
    accounting (planner calls are low-frequency).

    Args:
        coro_factory: Zero-arg callable returning the awaitable LLM operation.
        config: Rate-limit / timeout configuration (from ``agent.loop.llm_rate_limit``).
        thread_id: Optional thread id for retry telemetry.

    Returns:
        Result of ``coro_factory``.

    Raises:
        EnhancedTimeoutError: When timeout retries are exhausted.
        Exception: Propagates non-retriable provider errors.
    """
    timeout_attempts = 0
    rate_limit_attempts = 0
    max_timeout_attempts = config.max_timeout_retries + 1 if config.retry_on_timeout else 1
    max_rate_limit_attempts = config.max_rate_limit_retries + 1 if config.retry_on_rate_limit else 1

    while True:
        eff_timeout = _calc_retry_timeout(
            config.call_timeout_seconds,
            timeout_attempts,
            cap=config.call_timeout_max_seconds,
            multiplier=config.timeout_retry_multiplier,
        )

        try:
            return await asyncio.wait_for(coro_factory(), timeout=eff_timeout)

        except TimeoutError:
            timeout_attempts += 1
            if timeout_attempts < max_timeout_attempts:
                backoff = 1.0 * timeout_attempts
                logger.warning(
                    "Direct LLM timeout (attempt %d/%d, %ds) - retrying in %.1fs (thread_id=%s)",
                    timeout_attempts,
                    max_timeout_attempts,
                    eff_timeout,
                    backoff,
                    thread_id,
                )
                _emit_retry_event(
                    attempt=timeout_attempts,
                    max_attempts=max_timeout_attempts,
                    error_type="timeout",
                    thread_id=thread_id,
                )
                await asyncio.sleep(backoff)
                continue

            logger.error(
                "Direct LLM exceeded timeout after %d attempts (%ds final, thread_id=%s)",
                max_timeout_attempts,
                eff_timeout,
                thread_id,
            )
            raise EnhancedTimeoutError(
                timeout_seconds=eff_timeout,
                retries=max_timeout_attempts - 1,
                prompt_chars=0,
                thread_id=thread_id,
            ) from None

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            if _is_api_rate_limit_error(exc):
                rate_limit_attempts += 1
                rate_limit_info = _extract_rate_limit_info(exc)
                logger.warning(
                    "Direct LLM rate limited: retry_after=%ss rpm_hint=%s provider=%s "
                    "(thread_id=%s)",
                    rate_limit_info["retry_after_seconds"] or "none",
                    rate_limit_info["rpm_limit_hint"] or "none",
                    rate_limit_info["provider_name"] or "unknown",
                    thread_id,
                )
                if rate_limit_attempts < max_rate_limit_attempts:
                    backoff = _calc_rate_limit_backoff(
                        rate_limit_attempts - 1,
                        exc,
                        base=config.rate_limit_backoff_base,
                        backoff_max=config.rate_limit_backoff_max,
                        respect_retry_after=config.respect_retry_after_header,
                    )
                    logger.warning(
                        "Direct LLM 429 (attempt %d/%d) - retrying in %.1fs (thread_id=%s)",
                        rate_limit_attempts,
                        max_rate_limit_attempts,
                        backoff,
                        thread_id,
                    )
                    _emit_retry_event(
                        attempt=rate_limit_attempts,
                        max_attempts=max_rate_limit_attempts,
                        error_type="rate_limit",
                        thread_id=thread_id,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise

            if _is_transient_connection_error(exc):
                connection_attempts = 0
                max_connection_attempts = 3
                while connection_attempts < max_connection_attempts:
                    connection_attempts += 1
                    backoff = 2.0 * connection_attempts
                    logger.warning(
                        "Direct LLM connection error (attempt %d/%d) - retrying in %.1fs "
                        "(thread_id=%s): %s",
                        connection_attempts,
                        max_connection_attempts,
                        backoff,
                        thread_id,
                        str(exc)[:100],
                    )
                    await asyncio.sleep(backoff)
                    try:
                        return await asyncio.wait_for(coro_factory(), timeout=eff_timeout)
                    except Exception as retry_exc:
                        if not _is_transient_connection_error(retry_exc):
                            raise
                        exc = retry_exc
                        continue
                raise

            raise
