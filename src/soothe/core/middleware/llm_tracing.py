"""LLM request/response tracing middleware for debugging.

IMPORTANT: This middleware uses langchain's hook-based middleware pattern.
- Implement awrap_model_call() to wrap async LLM invocations
- The framework calls this hook, NOT run()/arun() methods
- See IG-141 for the correct middleware implementation pattern
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware, ContextT, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class LLMTracingMiddleware(AgentMiddleware):
    """Middleware that traces LLM request/response lifecycle for debugging.

    Logs comprehensive debug information including:
    - Request details: message count, total length, system prompt preview
    - Response details: token usage, latency, response preview
    - Request/response correlation via unique trace IDs

    This middleware is useful for:
    - Debugging prompt construction issues
    - Analyzing token usage patterns
    - Profiling LLM latency
    - Understanding message flow

    Example log output:
        [LLM Trace #123] Request: 3 messages (1.2K chars)
        [LLM Trace #123] System: "You are a helpful assistant..."
        [LLM Trace #123] Response: 256 tokens, 340ms, "Here's the answer..."
    """

    def __init__(self, *, log_preview_length: int = 200) -> None:
        """Initialize LLM tracing middleware.

        Args:
            log_preview_length: Maximum characters to log for message previews (default: 200).
        """
        self._log_preview_length = log_preview_length
        self._trace_counter = 0
        logger.info("[LLM Tracing] Middleware initialized (preview_length=%d)", log_preview_length)

    def modify_request(self, request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
        """Log request details before LLM call.

        Args:
            request: Model request to trace.

        Returns:
            Unmodified request (passthrough).
        """
        return request

    def modify_response(self, response: ModelResponse[Any]) -> ModelResponse[Any]:
        """Log response details after LLM call.

        Args:
            response: Model response to trace.

        Returns:
            Unmodified response (passthrough).
        """
        return response

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Trace async LLM request/response lifecycle.

        This is the correct langchain middleware hook that wraps model calls.
        The framework calls this method, NOT run()/arun() which are unused.

        Args:
            request: Model request to process.
            handler: Next async handler in middleware chain.

        Returns:
            Model response from handler.
        """
        trace_id = self._next_trace_id()
        self._log_request(trace_id, request)

        start_time = time.perf_counter()
        try:
            response = await handler(request)
        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            self._log_error(trace_id, e, duration_ms)
            raise
        else:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            self._log_response(trace_id, response, duration_ms)
            return response

    def _next_trace_id(self) -> int:
        """Generate next trace ID."""
        self._trace_counter += 1
        return self._trace_counter

    def _log_request(self, trace_id: int, request: ModelRequest[ContextT]) -> None:
        """Log comprehensive request details.

        Args:
            trace_id: Unique trace identifier.
            request: Model request to log.
        """
        messages = request.messages

        # Count messages and calculate total length
        message_count = len(messages)
        total_chars = sum(
            len(msg.content) if isinstance(msg.content, str) else len(str(msg.content)) for msg in messages
        )

        logger.debug(
            "[LLM Trace #%d] Request: %d messages (%s chars)",
            trace_id,
            message_count,
            self._format_size(total_chars),
        )

        # Log message breakdown by type
        system_count = sum(1 for msg in messages if isinstance(msg, SystemMessage))
        human_count = sum(1 for msg in messages if isinstance(msg, HumanMessage))
        ai_count = sum(1 for msg in messages if isinstance(msg, AIMessage))

        if system_count > 0 or human_count > 0 or ai_count > 0:
            logger.debug(
                "[LLM Trace #%d] Messages: system=%d, human=%d, ai=%d",
                trace_id,
                system_count,
                human_count,
                ai_count,
            )

        # Log system prompt preview
        for msg in messages:
            if isinstance(msg, SystemMessage):
                preview = self._preview(msg.content)
                logger.debug(
                    "[LLM Trace #%d] System prompt (preview): %s",
                    trace_id,
                    preview,
                )
                break

        # Log state/configurable info
        if hasattr(request, "state") and request.state:
            state_keys = list(request.state.keys()) if hasattr(request.state, "keys") else []
            if state_keys:
                logger.debug(
                    "[LLM Trace #%d] State keys: %s",
                    trace_id,
                    state_keys,
                )

        if hasattr(request, "config") and request.config:
            configurable = request.config.get("configurable", {})
            thread_id = configurable.get("thread_id", "unknown")
            if thread_id != "unknown":
                logger.debug(
                    "[LLM Trace #%d] Thread: %s",
                    trace_id,
                    thread_id,
                )

    def _log_response(self, trace_id: int, response: ModelResponse[Any], duration_ms: int) -> None:
        """Log comprehensive response details.

        Args:
            trace_id: Unique trace identifier.
            response: Model response to log.
            duration_ms: Request duration in milliseconds.
        """
        # ModelResponse has 'result' attribute containing messages
        messages = response.result

        # Find the latest AI message (LLM response)
        ai_message = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                ai_message = msg
                break

        if ai_message:
            # Log response preview
            content_preview = self._preview(ai_message.content)
            logger.debug(
                "[LLM Trace #%d] Response: %dms, preview: %s",
                trace_id,
                duration_ms,
                content_preview,
            )

            # Log token usage if available
            if hasattr(ai_message, "response_metadata"):
                metadata = ai_message.response_metadata
                token_usage = metadata.get("token_usage", {})
                if token_usage:
                    prompt_tokens = token_usage.get("prompt_tokens", 0)
                    completion_tokens = token_usage.get("completion_tokens", 0)
                    total_tokens = token_usage.get("total_tokens", 0)

                    logger.debug(
                        "[LLM Trace #%d] Token usage: prompt=%d, completion=%d, total=%d",
                        trace_id,
                        prompt_tokens,
                        completion_tokens,
                        total_tokens,
                    )

            # Log tool calls if present
            if hasattr(ai_message, "tool_calls") and ai_message.tool_calls:
                tool_count = len(ai_message.tool_calls)
                tool_names = [tc.get("name", "unknown") for tc in ai_message.tool_calls]
                logger.debug(
                    "[LLM Trace #%d] Tool calls: %d (%s)",
                    trace_id,
                    tool_count,
                    ", ".join(tool_names[:5]),
                )
        else:
            logger.debug(
                "[LLM Trace #%d] Response: %dms (no AI message in response)",
                trace_id,
                duration_ms,
            )

    def _log_error(self, trace_id: int, error: Exception, duration_ms: int) -> None:
        """Log error details.

        Args:
            trace_id: Unique trace identifier.
            error: Exception that occurred.
            duration_ms: Request duration before failure.
        """
        logger.error(
            "[LLM Trace #%d] Error after %dms: %s: %s",
            trace_id,
            duration_ms,
            type(error).__name__,
            str(error)[:200],
        )

    def _preview(self, content: str | list | dict) -> str:
        """Create preview of content.

        Args:
            content: Content to preview.

        Returns:
            Preview string.
        """
        if isinstance(content, str):
            preview = content.strip()
            if len(preview) > self._log_preview_length:
                preview = preview[: self._log_preview_length - 3] + "..."
            return preview

        if isinstance(content, list):
            # Handle list of content blocks
            return f"[list of {len(content)} items]"

        if isinstance(content, dict):
            return f"[dict with keys: {list(content.keys())[:5]}]"

        return str(content)[: self._log_preview_length]

    def _format_size(self, char_count: int) -> str:
        """Format character count as human-readable size.

        Args:
            char_count: Number of characters.

        Returns:
            Human-readable size string (e.g., "1.2K", "3.4M").
        """
        _kilo = 1000
        _mega = 1_000_000

        if char_count < _kilo:
            return str(char_count)

        if char_count < _mega:
            return f"{char_count / _kilo:.1f}K"

        return f"{char_count / _mega:.1f}M"
