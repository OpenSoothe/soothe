"""LLM tracing wrapper for direct model calls outside CoreAgent.

Use this wrapper when calling model.ainvoke() directly outside the
CoreAgent middleware chain (e.g., in classifier, consensus, criticality, etc.).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)


class LLMTracingWrapper:
    """Wraps BaseChatModel to add tracing for non-CoreAgent calls.

    This wrapper provides the same tracing capabilities as LLMTracingMiddleware
    for components that call LLMs directly outside the CoreAgent middleware chain.

    Use this when:
    - Calling model.ainvoke() from classifier, consensus, criticality, etc.
    - Direct model invocations that need tracing but don't go through CoreAgent

    Example:
        >>> from soothe.core.middleware._wrapper import LLMTracingWrapper
        >>> wrapped_model = LLMTracingWrapper(model)
        >>> response = await wrapped_model.ainvoke(
        ...     messages,
        ...     config={
        ...         "metadata": create_llm_call_metadata(
        ...             purpose="classify",
        ...             component="classifier",
        ...         )
        ...     },
        ... )
    """

    def __init__(self, model: BaseChatModel) -> None:
        """Initialize wrapper with underlying model.

        Args:
            model: BaseChatModel instance to wrap
        """
        self._model = model
        self._trace_counter = 0
        logger.debug("[LLM Tracing Wrapper] Initialized for %s", type(model).__name__)

    async def ainvoke(
        self,
        messages: Any,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Invoke model with automatic tracing.

        Args:
            messages: Messages to send to model
            config: Config dict (metadata should contain soothe_call_* fields)
            **kwargs: Additional arguments passed to underlying model

        Returns:
            Model response

        Raises:
            Exception: Any exception from underlying model.ainvoke()
        """
        trace_id = self._next_trace_id()
        self._log_request(trace_id, messages, config)
        start_time = time.perf_counter()

        try:
            response = await self._model.ainvoke(messages, config=config, **kwargs)
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

    def _log_request(self, trace_id: int, messages: Any, config: dict[str, Any] | None) -> None:
        """Log request details.

        Args:
            trace_id: Unique trace identifier
            messages: Messages to log
            config: Config with metadata
        """
        # Count messages and calculate total length
        if hasattr(messages, "__iter__") and not isinstance(messages, str):
            msg_list = list(messages)
            message_count = len(msg_list)
            total_chars = sum(
                len(m.content)
                if hasattr(m, "content") and isinstance(m.content, str)
                else len(str(m.content))
                if hasattr(m, "content")
                else len(str(m))
                for m in msg_list
            )
        else:
            message_count = 1
            total_chars = len(str(messages))

        logger.debug(
            "[LLM Trace #%d] Request: %d messages (%s chars)",
            trace_id,
            message_count,
            self._format_size(total_chars),
        )

        # Count message types
        if hasattr(messages, "__iter__") and not isinstance(messages, str):
            system_count = sum(1 for m in messages if isinstance(m, SystemMessage))
            human_count = sum(1 for m in messages if isinstance(m, HumanMessage))
            ai_count = sum(1 for m in messages if isinstance(m, AIMessage))

            if system_count > 0 or human_count > 0 or ai_count > 0:
                # Detect RFC-207 pattern (SystemMessage + HumanMessage)
                rfc207_pattern = system_count == 1 and human_count == 1 and ai_count == 0

                logger.debug(
                    "[LLM Trace #%d] Messages: system=%d, human=%d, ai=%d%s",
                    trace_id,
                    system_count,
                    human_count,
                    ai_count,
                    " (RFC-207 separation)" if rfc207_pattern else "",
                )

        # Extract metadata tags
        if config:
            metadata = config.get("metadata", {})

            purpose = metadata.get("soothe_call_purpose", "unknown")
            component = metadata.get("soothe_call_component", "unknown")
            phase = metadata.get("soothe_call_phase", "unknown")

            if purpose != "unknown":
                logger.debug(
                    "[LLM Trace #%d] Purpose: %s (component=%s, phase=%s)",
                    trace_id,
                    purpose,
                    component,
                    phase,
                )

            # Purpose-specific previews
            if purpose == "classify" and hasattr(messages, "__iter__"):
                # Show user query for classification
                for msg in messages:
                    if isinstance(msg, HumanMessage):
                        query_preview = str(msg.content)[:200]
                        logger.debug(
                            "[LLM Trace #%d] Query: %s",
                            trace_id,
                            query_preview,
                        )
                        break

    def _log_response(self, trace_id: int, response: Any, duration_ms: int) -> None:
        """Log response details.

        Args:
            trace_id: Unique trace identifier
            response: Model response
            duration_ms: Request duration in milliseconds
        """
        if hasattr(response, "content"):
            preview = str(response.content)[:200]
            logger.debug(
                "[LLM Trace #%d] Response: %dms, preview: %s",
                trace_id,
                duration_ms,
                preview,
            )

            # Log token usage if available
            if hasattr(response, "response_metadata"):
                token_usage = response.response_metadata.get("token_usage", {})
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
            if hasattr(response, "tool_calls") and response.tool_calls:
                tool_count = len(response.tool_calls)
                tool_names = [tc.get("name", "unknown") for tc in response.tool_calls]
                logger.debug(
                    "[LLM Trace #%d] Tool calls: %d (%s)",
                    trace_id,
                    tool_count,
                    ", ".join(tool_names[:5]),
                )
        else:
            logger.debug(
                "[LLM Trace #%d] Response: %dms (no content field)",
                trace_id,
                duration_ms,
            )

    def _log_error(self, trace_id: int, error: Exception, duration_ms: int) -> None:
        """Log error details.

        Args:
            trace_id: Unique trace identifier
            error: Exception that occurred
            duration_ms: Request duration before failure
        """
        logger.error(
            "[LLM Trace #%d] Error after %dms: %s: %s",
            trace_id,
            duration_ms,
            type(error).__name__,
            str(error)[:200],
        )

    def _format_size(self, char_count: int) -> str:
        """Format character count as human-readable size.

        Args:
            char_count: Number of characters

        Returns:
            Human-readable size string (e.g., "1.2K", "3.4M")
        """
        _kilo = 1000
        _mega = 1_000_000

        if char_count < _kilo:
            return str(char_count)

        if char_count < _mega:
            return f"{char_count / _kilo:.1f}K"

        return f"{char_count / _mega:.1f}M"
