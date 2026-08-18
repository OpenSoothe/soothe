"""Langfuse parent span for the evaluate station.

Wraps inventory + assess so LangChain planner generations share one
``evaluate`` observation on the goal-loop trace.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from soothe.utils.observability.langfuse._names import evaluate_langfuse_run_display_name
from soothe.utils.observability.langfuse._station_span import (
    bind_planner_langfuse_trace,
    restore_planner_langfuse_trace,
    station_langfuse_span,
)

__all__ = [
    "bind_planner_langfuse_trace",
    "evaluate_langfuse_span",
    "evaluate_langfuse_span_async",
    "restore_planner_langfuse_trace",
]


@contextmanager
def evaluate_langfuse_span(
    *,
    soothe_config: Any | None,
    goal_trace: Any | None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Any | None]:
    """Sync context manager: parent ``evaluate`` span on the goal-loop trace."""
    with station_langfuse_span(
        soothe_config=soothe_config,
        goal_trace=goal_trace,
        station="evaluate",
        run_name_fn=evaluate_langfuse_run_display_name,
        metadata=metadata,
        log_label="evaluate",
    ) as span:
        yield span


@asynccontextmanager
async def evaluate_langfuse_span_async(
    *,
    soothe_config: Any | None,
    goal_trace: Any | None,
    metadata: dict[str, Any] | None = None,
) -> AsyncIterator[Any | None]:
    """Async wrapper around :func:`evaluate_langfuse_span` for station nodes."""
    with evaluate_langfuse_span(
        soothe_config=soothe_config,
        goal_trace=goal_trace,
        metadata=metadata,
    ) as span:
        yield span
