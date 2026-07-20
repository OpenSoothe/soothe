"""Profiling for model-call latency analysis across soothe_deepagents and Soothe middleware.

Use when debugging unexplained gaps between Langfuse ``model`` spans and LLM
generation spans.

Enable via config:
    observability:
      profile_model_calls: true

Log prefixes:
- ``[DeepAgentsProfiler]`` — outer soothe_deepagents stack (TodoList, Filesystem,
  SubAgent, Summarization, PatchToolCalls) patched at CoreAgent build time
- ``[ModelProfiler]`` / ``[InnerProfiler]`` / ``[LLMProfiler]`` — Soothe
  middleware stack inserted via ``build_soothe_middleware_stack``
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware

if TYPE_CHECKING:
    from langchain.agents.request import ModelRequest
    from langchain.agents.response import ModelResponse

    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)

_BLOCK_TAGS: tuple[tuple[str, str], ...] = (
    ("AGENT_INSTRUCTIONS", "agent_instructions"),
    ("AVAILABLE_SKILLS", "skills"),
    ("AVAILABLE_MCP_TOOLS", "mcp"),
    ("AVAILABLE_TOOLS", "available_tools"),
    ("WORKSPACE_RULES", "workspace_rules"),
    ("TOOL_ORCHESTRATION", "orchestration"),
)


def _block_char_sizes(text: str) -> dict[str, int]:
    """Approximate per-block char counts in the effective system prompt."""
    sizes: dict[str, int] = {label: 0 for _, label in _BLOCK_TAGS}
    upper = text.upper()
    for tag, label in _BLOCK_TAGS:
        open_tag = f"<{tag}"
        close_tag = f"</{tag}>"
        start = 0
        while True:
            idx = upper.find(open_tag, start)
            if idx < 0:
                break
            end = upper.find(close_tag, idx)
            if end < 0:
                break
            end += len(close_tag)
            sizes[label] += end - idx
            start = end
    sizes["base"] = max(0, len(text) - sum(sizes.values()))
    return sizes


# Track chain depth for nested Soothe middleware profiler calls
_chain_depth = 0

_DEEPAGENTS_PATCHED_ATTR = "_soothe_deepagents_profiler_patched"

_DEEPAGENTS_PROFILER_TARGETS: tuple[tuple[str, str], ...] = (
    ("langchain.agents.middleware", "TodoListMiddleware"),
    ("soothe_deepagents.middleware.filesystem", "FilesystemMiddleware"),
    ("soothe_deepagents.middleware.subagents", "SubAgentMiddleware"),
    ("soothe_deepagents.middleware.summarization", "SummarizationMiddleware"),
    # PatchToolCallsMiddleware only implements before_agent; patching awrap_model_call
    # would register it in the async model-call chain and break astream().
)


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

    def __init__(self, enabled: bool = False) -> None:
        """Initialize profiler middleware.

        Args:
            enabled: When True, log model-call timing checkpoints.
        """
        super().__init__()
        self._enabled = enabled

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
        if sys_chars > 0 and isinstance(request.system_message.content, str):
            blocks = _block_char_sizes(request.system_message.content)
            logger.info(
                "[ModelProfiler] SYS_BLOCKS base=%d agent_instructions=%d "
                "skills=%d mcp=%d available_tools=%d workspace_rules=%d orchestration=%d",
                blocks.get("base", 0),
                blocks.get("agent_instructions", 0),
                blocks.get("skills", 0),
                blocks.get("mcp", 0),
                blocks.get("available_tools", 0),
                blocks.get("workspace_rules", 0),
                blocks.get("orchestration", 0),
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

    def __init__(self, enabled: bool = False) -> None:
        """Initialize inner profiler middleware.

        Args:
            enabled: When True, log inner handler timing checkpoints.
        """
        super().__init__()
        self._enabled = enabled

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
    This captures timing after Soothe middleware (PerTurnModel, caching).

    SummarizationMiddleware runs in the soothe_deepagents stack before the Soothe
    middleware slice; see ``[DeepAgentsProfiler]`` logs when profiling is enabled.
    """

    name = "LLMCallProfilerMiddleware"

    def __init__(self, enabled: bool = False) -> None:
        """Initialize LLM profiler middleware.

        Args:
            enabled: When True, log LLM API timing checkpoints.
        """
        super().__init__()
        self._enabled = enabled

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
            "[LLMProfiler] HANDLER_CALL depth=%d pre_llm=%.3fms "
            "(PerTurnModel + Anthropic caching; summarization is outer)",
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

            # If pre_llm_ms is large, latency is in PerTurnModel or Anthropic caching
            if pre_llm_ms > 1000:  # >1s is suspicious
                logger.warning(
                    "[LLMProfiler] CACHING_OR_MODEL_OVERRIDE_LATENCY depth=%d pre=%.3fs > 1s",
                    depth,
                    pre_llm_ms / 1000,
                )


def is_profiler_enabled(config: SootheConfig) -> bool:
    """Return whether model call profiling is enabled in config."""
    return config.observability.profile_model_calls


def _implements_model_call_hook(cls: type) -> bool:
    """Return True when ``cls`` overrides sync or async model-call middleware."""
    return (
        cls.wrap_model_call is not AgentMiddleware.wrap_model_call
        or cls.awrap_model_call is not AgentMiddleware.awrap_model_call
    )


def install_model_call_profiler(*, enabled: bool) -> None:
    """Install soothe_deepagents outer-middleware timing patches when profiling is on.

    Soothe profiler middleware is added separately by ``build_soothe_middleware_stack``.
    Both layers honor ``observability.profile_model_calls``. Idempotent per process.

    Args:
        enabled: When False, does nothing. When True, wraps ``awrap_model_call`` on
            outer soothe_deepagents middleware classes once per process.
    """
    if not enabled:
        return

    for module_path, class_name in _DEEPAGENTS_PROFILER_TARGETS:
        try:
            module = __import__(module_path, fromlist=[class_name])
            cls = getattr(module, class_name)
        except (ImportError, AttributeError):
            logger.debug(
                "[DeepAgentsProfiler] Skip %s.%s (not available)",
                module_path,
                class_name,
            )
            continue
        if not _implements_model_call_hook(cls):
            logger.debug(
                "[DeepAgentsProfiler] Skip %s (no model-call hook)",
                class_name,
            )
            continue
        _patch_deepagents_awrap_model_call(cls, class_name)


def _patch_deepagents_awrap_model_call(cls: type, label: str) -> None:
    """Wrap ``awrap_model_call`` on a soothe_deepagents middleware class with timing logs."""
    if getattr(cls, _DEEPAGENTS_PATCHED_ATTR, False):
        return

    if cls.awrap_model_call is AgentMiddleware.awrap_model_call:
        logger.debug(
            "[DeepAgentsProfiler] Skip %s (sync-only wrap_model_call)",
            label,
        )
        return

    original = cls.awrap_model_call
    if original is None:
        return

    async def awrap_model_call(
        self: Any,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        entry_time = time.perf_counter()
        handler_start: float | None = None

        async def timed_handler(inner_request: Any) -> Any:
            nonlocal handler_start
            handler_start = time.perf_counter()
            return await handler(inner_request)

        try:
            return await original(self, request, timed_handler)
        finally:
            exit_time = time.perf_counter()
            if handler_start is None:
                logger.info(
                    "[DeepAgentsProfiler] %s total=%.3fms (handler not reached)",
                    label,
                    (exit_time - entry_time) * 1000,
                )
            else:
                pre_ms = (handler_start - entry_time) * 1000
                handler_ms = (exit_time - handler_start) * 1000
                total_ms = (exit_time - entry_time) * 1000
                logger.info(
                    "[DeepAgentsProfiler] %s pre=%.3fms handler=%.3fms total=%.3fms",
                    label,
                    pre_ms,
                    handler_ms,
                    total_ms,
                )
                if label == "SummarizationMiddleware" and pre_ms > 1000:
                    logger.warning(
                        "[DeepAgentsProfiler] SummarizationMiddleware pre=%.3fs > 1s "
                        "(token counting / truncation)",
                        pre_ms / 1000,
                    )

    cls.awrap_model_call = awrap_model_call  # type: ignore[method-assign]
    setattr(cls, _DEEPAGENTS_PATCHED_ATTR, True)


__all__ = [
    "ModelCallProfilerMiddleware",
    "InnerModelCallProfilerMiddleware",
    "LLMCallProfilerMiddleware",
    "install_model_call_profiler",
    "is_profiler_enabled",
]
