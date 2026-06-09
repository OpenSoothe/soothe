"""Profiling middleware for model call timing analysis (IG-XXX).

This middleware wraps the model call chain to trace where time is spent
between the model node entry and the actual LLM API call. Use when debugging
unexplained latency gaps in Langfuse traces.

Enable via config:
    observability:
      profile_model_calls: true

Or via environment:
    SOOTHE_PROFILE_MODEL_CALLS=true

The profiler logs timing at these checkpoints:
- PROFILER_ENTRY: When awrap_model_call starts
- PROFILER_HANDLER_CALL: When calling the next handler (inner middleware or LLM)
- PROFILER_HANDLER_RETURN: When handler returns
- PROFILER_EXIT: When awrap_model_call exits

Example log output:
    [ModelProfiler] ENTRY chain_depth=1 tools=45 input_tokens=13519
    [ModelProfiler] HANDLER_CALL chain_depth=1 after=0.002s
    [ModelProfiler] HANDLER_RETURN chain_depth=1 handler_time=2.986s
    [ModelProfiler] EXIT chain_depth=1 total=42.67s pre_handler=39.68s
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware

if TYPE_CHECKING:
    from langchain.agents.request import ModelRequest
    from langchain.agents.response import ModelResponse

logger = logging.getLogger(__name__)

# Environment variable to enable profiling
_PROFILER_ENABLED = os.environ.get("SOOTHE_PROFILE_MODEL_CALLS", "").lower() in ("true", "1", "yes")

# Track chain depth for nested middleware calls
_chain_depth = 0


class ModelCallProfilerMiddleware(AgentMiddleware):
    """Middleware that profiles model call timing for latency debugging.

    This middleware should be inserted at the START of the middleware chain
    to capture the full timing picture. It wraps awrap_model_call to measure:
    - Pre-handler time (middleware chain processing before LLM)
    - Handler time (actual LLM API call)
    - Post-handler time (middleware chain processing after LLM)

    The pre-handler time includes all inner middleware processing plus
    any Langfuse/LangSmith callback overhead.
    """

    name = "ModelCallProfilerMiddleware"

    def __init__(self, enabled: bool | None = None) -> None:
        """Initialize profiler middleware.

        Args:
            enabled: Override environment variable. If None, uses SOOTHE_PROFILE_MODEL_CALLS.
        """
        super().__init__()
        self._enabled = enabled if enabled is not None else _PROFILER_ENABLED

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        """Sync wrapper (not typically used for async LLM calls)."""
        if not self._enabled:
            return handler(request)

        global _chain_depth
        _chain_depth += 1
        depth = _chain_depth
        entry_time = time.perf_counter()

        # Count tools and estimate input size
        tool_count = len(request.tools) if request.tools else 0
        msg_count = len(request.messages) if request.messages else 0
        input_chars = sum(len(str(m.content)) for m in request.messages) if request.messages else 0

        logger.info(
            "[ModelProfiler] ENTRY depth=%d tools=%d msgs=%d chars=%d (sync)",
            depth,
            tool_count,
            msg_count,
            input_chars,
        )

        # Call handler
        handler_start = time.perf_counter()
        pre_handler_ms = (handler_start - entry_time) * 1000

        logger.info(
            "[ModelProfiler] HANDLER_CALL depth=%d pre_handler=%.3fms (sync)",
            depth,
            pre_handler_ms,
        )

        try:
            response = handler(request)
            handler_end = time.perf_counter()
            handler_ms = (handler_end - handler_start) * 1000

            logger.info(
                "[ModelProfiler] HANDLER_RETURN depth=%d handler=%.3fms (sync)",
                depth,
                handler_ms,
            )
            return response
        finally:
            exit_time = time.perf_counter()
            total_ms = (exit_time - entry_time) * 1000
            post_handler_ms = (exit_time - handler_end) * 1000 if "handler_end" in dir() else 0
            _chain_depth -= 1

            logger.info(
                "[ModelProfiler] EXIT depth=%d total=%.3fms pre=%.3fms handler=%.3fms post=%.3fms (sync)",
                depth,
                total_ms,
                pre_handler_ms,
                handler_ms if "handler_ms" in dir() else 0,
                post_handler_ms,
            )

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Async wrapper that profiles the model call chain.

        This is the primary method for profiling async LLM calls.
        Logs timing at entry, before handler, after handler, and exit.
        """
        if not self._enabled:
            return await handler(request)

        global _chain_depth
        _chain_depth += 1
        depth = _chain_depth
        entry_time = time.perf_counter()

        # Count tools and estimate input size
        tool_count = len(request.tools) if request.tools else 0
        msg_count = len(request.messages) if request.messages else 0
        input_chars = 0
        if request.messages:
            for m in request.messages:
                content = m.content
                if isinstance(content, str):
                    input_chars += len(content)
                elif isinstance(content, list):
                    input_chars += sum(len(str(block)) for block in content)
                else:
                    input_chars += len(str(content))

        # System message size
        sys_chars = 0
        if request.system_message:
            content = request.system_message.content
            if isinstance(content, str):
                sys_chars = len(content)
            elif isinstance(content, list):
                sys_chars = sum(len(str(block)) for block in content)

        logger.info(
            "[ModelProfiler] ENTRY depth=%d tools=%d msgs=%d user_chars=%d sys_chars=%d",
            depth,
            tool_count,
            msg_count,
            input_chars,
            sys_chars,
        )

        # Call handler (this includes inner middleware + LLM call)
        handler_start = time.perf_counter()
        pre_handler_ms = (handler_start - entry_time) * 1000

        logger.info(
            "[ModelProfiler] HANDLER_CALL depth=%d pre_handler=%.3fms",
            depth,
            pre_handler_ms,
        )

        handler_end = None
        handler_ms = 0
        try:
            response = await handler(request)
            handler_end = time.perf_counter()
            handler_ms = (handler_end - handler_start) * 1000

            logger.info(
                "[ModelProfiler] HANDLER_RETURN depth=%d handler=%.3fms",
                depth,
                handler_ms,
            )
            return response
        finally:
            exit_time = time.perf_counter()
            total_ms = (exit_time - entry_time) * 1000

            # Calculate post-handler time
            post_handler_ms = 0
            if handler_end:
                post_handler_ms = (exit_time - handler_end) * 1000

            _chain_depth -= 1

            # The key insight: pre_handler_ms includes ALL inner middleware processing
            # If pre_handler_ms is large (e.g., 39s) and handler_ms is small (e.g., 3s),
            # then the latency gap is in inner middleware or Langfuse/LangSmith callbacks
            logger.info(
                "[ModelProfiler] EXIT depth=%d total=%.3fms pre=%.3fms handler=%.3fms post=%.3fms",
                depth,
                total_ms,
                pre_handler_ms,
                handler_ms,
                post_handler_ms,
            )

            # Warn if pre-handler time is suspiciously large
            if pre_handler_ms > 5000:  # >5s is suspicious
                logger.warning(
                    "[ModelProfiler] SUSPICIOUS_LATENCY depth=%d pre_handler=%.3fs > 5s "
                    "- investigate inner middleware chain",
                    depth,
                    pre_handler_ms / 1000,
                )


class InnerModelCallProfilerMiddleware(AgentMiddleware):
    """Middleware that profiles inner handler timing to pinpoint latency source.

    Insert this AFTER SystemPromptMiddleware but BEFORE LLMRateLimitMiddleware
    to capture timing after request modification but before rate limiting.

    This helps distinguish:
    - System prompt building time (captured in outer profiler's pre-handler)
    - Rate limiting wait time (captured between inner profiler's entry and handler)
    - Actual LLM call time (captured as handler time)
    """

    name = "InnerModelCallProfilerMiddleware"

    def __init__(self, enabled: bool | None = None) -> None:
        """Initialize inner profiler middleware.

        Args:
            enabled: Override environment variable. If None, uses SOOTHE_PROFILE_MODEL_CALLS.
        """
        super().__init__()
        self._enabled = enabled if enabled is not None else _PROFILER_ENABLED

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Async wrapper that profiles inner handler timing."""
        if not self._enabled:
            return await handler(request)

        global _chain_depth
        _chain_depth += 1
        depth = _chain_depth
        entry_time = time.perf_counter()

        logger.info(
            "[InnerProfiler] ENTRY depth=%d (after SystemPrompt, before RateLimiter)",
            depth,
        )

        handler_start = time.perf_counter()
        pre_inner_ms = (handler_start - entry_time) * 1000

        logger.info(
            "[InnerProfiler] HANDLER_CALL depth=%d pre_inner=%.3fms",
            depth,
            pre_inner_ms,
        )

        handler_end = None
        try:
            response = await handler(request)
            handler_end = time.perf_counter()
            handler_ms = (handler_end - handler_start) * 1000

            logger.info(
                "[InnerProfiler] HANDLER_RETURN depth=%d handler=%.3fms",
                depth,
                handler_ms,
            )
            return response
        finally:
            exit_time = time.perf_counter()
            total_ms = (exit_time - entry_time) * 1000
            _chain_depth -= 1

            # pre_inner_ms includes rate limiter wait + remaining middleware + LLM
            # If pre_inner_ms >> handler_ms, latency is in rate limiting or remaining middleware
            logger.info(
                "[InnerProfiler] EXIT depth=%d total=%.3fms pre=%.3fms handler=%.3fms",
                depth,
                total_ms,
                pre_inner_ms,
                handler_ms if handler_end else 0,
            )

            # Specific warning for rate limiter wait
            if pre_inner_ms > 30000:  # >30s suggests rate limiter wait
                logger.warning(
                    "[InnerProfiler] RATE_LIMIT_WAIT_SUSPECTED depth=%d pre=%.3fs > 30s",
                    depth,
                    pre_inner_ms / 1000,
                )


class LLMCallProfilerMiddleware(AgentMiddleware):
    """Middleware that wraps JUST before the LLM call to capture pure API latency.

    Insert this as the LAST middleware before the actual LLM ainvoke.
    This captures timing after ALL middleware processing.

    In the deepagents chain, this would be placed before:
    - SummarizationMiddleware (token counting)
    - AnthropicPromptCachingMiddleware (cache control injection)
    - The actual model.ainvoke()
    """

    name = "LLMCallProfilerMiddleware"

    def __init__(self, enabled: bool | None = None) -> None:
        """Initialize LLM profiler middleware.

        Args:
            enabled: Override environment variable. If None, uses SOOTHE_PROFILE_MODEL_CALLS.
        """
        super().__init__()
        self._enabled = enabled if enabled is not None else _PROFILER_ENABLED

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Async wrapper that profiles LLM API call timing."""
        if not self._enabled:
            return await handler(request)

        global _chain_depth
        _chain_depth += 1
        depth = _chain_depth
        entry_time = time.perf_counter()

        # Get model name for identification
        model_name = getattr(request.model, "model_name", None) or getattr(
            request.model, "model", None
        )
        model_name = str(model_name) if model_name else "unknown"

        logger.info(
            "[LLMProfiler] ENTRY depth=%d model=%s",
            depth,
            model_name,
        )

        handler_start = time.perf_counter()
        pre_llm_ms = (handler_start - entry_time) * 1000

        logger.info(
            "[LLMProfiler] HANDLER_CALL depth=%d pre_llm=%.3fms (includes summarization + caching)",
            depth,
            pre_llm_ms,
        )

        handler_end = None
        try:
            response = await handler(request)
            handler_end = time.perf_counter()
            handler_ms = (handler_end - handler_start) * 1000

            logger.info(
                "[LLMProfiler] HANDLER_RETURN depth=%d llm_api=%.3fms",
                depth,
                handler_ms,
            )
            return response
        finally:
            exit_time = time.perf_counter()
            total_ms = (exit_time - entry_time) * 1000
            _chain_depth -= 1

            logger.info(
                "[LLMProfiler] EXIT depth=%d total=%.3fms pre=%.3fms llm=%.3fms post=%.3fms",
                depth,
                total_ms,
                pre_llm_ms,
                handler_ms if handler_end else 0,
                (exit_time - handler_end) * 1000 if handler_end else 0,
            )

            # If pre_llm_ms is large, latency is in summarization/token counting
            if pre_llm_ms > 1000:  # >1s is suspicious for summarization
                logger.warning(
                    "[LLMProfiler] SUMMARIZATION_OR_CACHING_LATENCY depth=%d pre=%.3fs > 1s",
                    depth,
                    pre_llm_ms / 1000,
                )


def is_profiler_enabled() -> bool:
    """Check if model call profiling is enabled."""
    return _PROFILER_ENABLED


__all__ = [
    "ModelCallProfilerMiddleware",
    "InnerModelCallProfilerMiddleware",
    "LLMCallProfilerMiddleware",
    "is_profiler_enabled",
]
