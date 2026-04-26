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
from soothe.utils.text_preview import preview_first

logger = logging.getLogger(__name__)


class LLMTracingWrapper:
    """Wraps BaseChatModel to add tracing for non-CoreAgent calls.

    This wrapper provides the same tracing capabilities as LLMTracingMiddleware
    for components that call LLMs directly outside the CoreAgent middleware chain.

    Use this when:
    - Calling model.ainvoke() from classifier, consensus, criticality, etc.
    - Direct model invocations that need tracing but don't go through CoreAgent

    Example:
        >>> from soothe.core.llm import LLMTracingWrapper
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
        logger.debug("[LLM Trace] Wrapper initialized for %s", type(model).__name__)

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

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        """Delegate structured output to wrapped model.

        This method is needed for IntentClassifier which wraps the model
        with LLMTracingWrapper before calling with_structured_output().

        Args:
            schema: Pydantic schema for structured output.
            **kwargs: Additional arguments (method, etc.).

        Returns:
            Runnable with structured output support from underlying model.
        """
        return self._model.with_structured_output(schema, **kwargs)

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

        # Build compact message type breakdown
        msg_type_info = ""
        if hasattr(messages, "__iter__") and not isinstance(messages, str):
            system_count = sum(1 for m in messages if isinstance(m, SystemMessage))
            human_count = sum(1 for m in messages if isinstance(m, HumanMessage))
            ai_count = sum(1 for m in messages if isinstance(m, AIMessage))

            if system_count > 0 or human_count > 0 or ai_count > 0:
                parts = []
                if system_count > 0:
                    parts.append(f"sys:{system_count}")
                if human_count > 0:
                    parts.append(f"hum:{human_count}")
                if ai_count > 0:
                    parts.append(f"ai:{ai_count}")
                msg_type_info = " [" + ", ".join(parts) + "]"

                # Detect RFC-207 pattern (SystemMessage + HumanMessage)
                if system_count == 1 and human_count == 1 and ai_count == 0:
                    msg_type_info = " [RFC-207: sys:1, hum:1]"

        logger.debug(
            "[LLM Trace #%d] → %d msg%s (%s)",
            trace_id,
            message_count,
            msg_type_info,
            self._format_size(total_chars),
        )

        # Extract and combine metadata into single line
        if config:
            metadata = config.get("metadata", {})
            purpose = metadata.get("soothe_call_purpose", "unknown")

            if purpose != "unknown":
                component = metadata.get("soothe_call_component", "unknown")
                phase = metadata.get("soothe_call_phase", "unknown")
                logger.debug(
                    "[LLM Trace #%d]   purpose=%s, component=%s, phase=%s",
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
                            query_preview = preview_first(str(msg.content), 200)
                            logger.debug(
                                "[LLM Trace #%d]   query: %s",
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
            preview = preview_first(str(response.content), 200)

            # Build compact info string with tokens and tools
            info_parts = [f"{duration_ms}ms"]

            # Add token usage if available
            if hasattr(response, "response_metadata"):
                token_usage = response.response_metadata.get("token_usage", {})
                if token_usage:
                    prompt_tokens = token_usage.get("prompt_tokens", 0)
                    completion_tokens = token_usage.get("completion_tokens", 0)
                    total_tokens = token_usage.get("total_tokens", 0)
                    info_parts.append(
                        f"tok:{total_tokens} (p:{prompt_tokens}, c:{completion_tokens})"
                    )

            # Add tool call count if present
            if hasattr(response, "tool_calls") and response.tool_calls:
                tool_count = len(response.tool_calls)
                info_parts.append(f"tools:{tool_count}")

            logger.debug(
                "[LLM Trace #%d] ← %s | %s",
                trace_id,
                ", ".join(info_parts),
                preview,
            )

            # Log tool names separately if present (compact line)
            if hasattr(response, "tool_calls") and response.tool_calls:
                tool_names = [tc.get("name", "unknown") for tc in response.tool_calls]
                logger.debug(
                    "[LLM Trace #%d]   tools: %s",
                    trace_id,
                    ", ".join(tool_names[:5]),
                )
        else:
            logger.debug(
                "[LLM Trace #%d] ← %dms (no content)",
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
            "[LLM Trace #%d] ✗ %dms | %s: %s",
            trace_id,
            duration_ms,
            type(error).__name__,
            preview_first(str(error), 200),
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
