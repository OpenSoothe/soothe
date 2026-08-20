"""Langfuse parent span for the intake stage.

The pre-graph social gate builds its own RunnableConfig, so without a parent it
lands at the trace root instead of under a station observation. Unlike
``evaluate``, the span id is threaded explicitly through ``GoalLoopTrace``
rather than through OTEL ambient context because generator suspension points
could leak a current-span context manager into unrelated tasks.

The graph-entry classifier instead inherits the LangGraph node's RunnableConfig
so its model generation remains a child of the graph ``intake`` node.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.utils.observability.langfuse._client import host_langfuse_client
from soothe.utils.observability.langfuse._names import intake_langfuse_run_display_name

logger = logging.getLogger(__name__)


class IntakeLangfuseSpan:
    """Handle to the ``intake`` span; inert when Langfuse is unavailable."""

    __slots__ = ("_ended", "_span")

    def __init__(self, span: Any | None = None) -> None:
        self._span = span
        self._ended = False

    @property
    def parent_span_id(self) -> str | None:
        """Span id to nest intake generations under, when the span is live."""
        if self._span is None:
            return None
        span_id = getattr(self._span, "id", None)
        return str(span_id) if span_id else None

    def end(self, *, output: Any = None) -> None:
        """Close the span once; repeated calls and failures are ignored."""
        if self._span is None or self._ended:
            return
        self._ended = True
        try:
            if output is not None:
                self._span.update(output=output)
            self._span.end()
        except Exception:
            logger.debug("[Intake] Langfuse span end failed", exc_info=True)


def open_intake_langfuse_span(
    goal_trace: Any | None,
    *,
    metadata: dict[str, Any] | None = None,
    input_text: str | None = None,
) -> IntakeLangfuseSpan:
    """Open the ``intake`` span on the goal-loop trace.

    Args:
        goal_trace: Active ``GoalLoopTrace``; ``None`` yields an inert handle.
        metadata: Extra observation metadata.
        input_text: User submission recorded as span input.

    Returns:
        A handle whose ``parent_span_id`` is ``None`` when tracing is off.
    """
    if goal_trace is None:
        return IntakeLangfuseSpan()
    try:
        if not getattr(goal_trace, "enabled", False):
            return IntakeLangfuseSpan()
        trace_id = getattr(goal_trace, "trace_id", None)
        soothe_config = getattr(goal_trace, "soothe_config", None)
        if not trace_id or soothe_config is None:
            return IntakeLangfuseSpan()
    except Exception:
        return IntakeLangfuseSpan()

    trace_name = (soothe_config.observability.langfuse.trace_name or "").strip() or None
    try:
        client = host_langfuse_client(soothe_config)
        span = client.start_observation(
            trace_context={"trace_id": str(trace_id)},
            as_type="span",
            name=intake_langfuse_run_display_name(trace_name),
            input=input_text,
            metadata={
                "soothe_component": "intake",
                "soothe_station": "intake",
                **(metadata or {}),
            },
        )
    except Exception:
        logger.debug("[Intake] Langfuse span unavailable", exc_info=True)
        return IntakeLangfuseSpan()
    return IntakeLangfuseSpan(span)


__all__ = ["IntakeLangfuseSpan", "open_intake_langfuse_span"]
