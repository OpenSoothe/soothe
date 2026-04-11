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

from soothe.utils.text_preview import preview, preview_first

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
        """Log compact request details in structured format.

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

        # Message breakdown by type
        system_count = sum(1 for msg in messages if isinstance(msg, SystemMessage))
        human_count = sum(1 for msg in messages if isinstance(msg, HumanMessage))
        ai_count = sum(1 for msg in messages if isinstance(msg, AIMessage))

        # Compact request summary in dict format
        req_summary = {
            "msg_count": message_count,
            "chars": self._format_size(total_chars),
            "types": {"sys": system_count, "human": human_count, "ai": ai_count},
        }

        # Extract metadata tags (IG-143)
        if hasattr(request, "config") and request.config:
            metadata = request.config.get("metadata", {})
            purpose = metadata.get("soothe_call_purpose", "unknown")
            if purpose != "unknown":
                req_summary["purpose"] = purpose
                req_summary["component"] = metadata.get("soothe_call_component", "unknown")
                req_summary["phase"] = metadata.get("soothe_call_phase", "unknown")

            # Purpose-specific: include query/goal preview
            if purpose in ("classify", "plan"):
                for msg in messages:
                    if isinstance(msg, HumanMessage):
                        preview_len = 200 if purpose == "classify" else 400
                        req_summary["input"] = self._preview(msg.content, max_length=preview_len)
                        break

            # Thread ID
            configurable = request.config.get("configurable", {})
            thread_id = configurable.get("thread_id", "unknown")
            if thread_id != "unknown":
                req_summary["thread"] = thread_id

        # State keys
        if hasattr(request, "state") and request.state:
            state_keys = list(request.state.keys()) if hasattr(request.state, "keys") else []
            if state_keys:
                req_summary["state"] = state_keys[:5]  # Limit to first 5 keys

        logger.debug("[LLM Trace #%d] Request: %s", trace_id, req_summary)

    def _log_response(self, trace_id: int, response: ModelResponse[Any], duration_ms: int) -> None:
        """Log compact response details in structured format.

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
            # Compact response summary in dict format
            resp_summary = {
                "duration_ms": duration_ms,
                "preview": self._preview(ai_message.content),
            }

            # Token usage if available
            if hasattr(ai_message, "response_metadata"):
                metadata = ai_message.response_metadata
                token_usage = metadata.get("token_usage", {})
                if token_usage:
                    resp_summary["tokens"] = {
                        "prompt": token_usage.get("prompt_tokens", 0),
                        "completion": token_usage.get("completion_tokens", 0),
                        "total": token_usage.get("total_tokens", 0),
                    }

            # Tool calls if present
            if hasattr(ai_message, "tool_calls") and ai_message.tool_calls:
                tool_names = [tc.get("name", "unknown") for tc in ai_message.tool_calls[:5]]
                resp_summary["tools"] = {"count": len(ai_message.tool_calls), "names": tool_names}

            logger.debug("[LLM Trace #%d] Response: %s", trace_id, resp_summary)
        else:
            logger.debug(
                "[LLM Trace #%d] Response: %s", trace_id, {"duration_ms": duration_ms, "error": "no AI message"}
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
            preview_first(str(error), 200),
        )

    def _preview(self, content: str | list | dict, max_length: int | None = None) -> str:
        """Create preview of content.

        Args:
            content: Content to preview.
            max_length: Optional override for preview length (default: self._log_preview_length).

        Returns:
            Preview string.
        """
        length = max_length or self._log_preview_length

        if isinstance(content, str):
            return preview(content.strip(), mode="chars", first=length, marker="...")

        if isinstance(content, list):
            # Handle list of content blocks
            return f"[list of {len(content)} items]"

        if isinstance(content, dict):
            return f"[dict with keys: {list(content.keys())[:5]}]"

        return preview(str(content), mode="chars", first=length, marker="...")

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
