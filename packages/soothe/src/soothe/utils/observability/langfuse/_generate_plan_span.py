"""Langfuse parent span for the generate_plan station.

Pins planner LLM runs to the goal-loop trace for the duration of
``node_plan_generate`` (full and lightweight paths).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from soothe.utils.observability.langfuse._names import generate_plan_langfuse_run_display_name
from soothe.utils.observability.langfuse._station_span import station_langfuse_span

__all__ = [
    "generate_plan_langfuse_span",
    "generate_plan_langfuse_span_async",
]


@contextmanager
def generate_plan_langfuse_span(
    *,
    soothe_config: Any | None,
    goal_trace: Any | None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Any | None]:
    """Sync context manager: parent ``generate-plan`` span on the goal-loop trace."""
    with station_langfuse_span(
        soothe_config=soothe_config,
        goal_trace=goal_trace,
        station="generate_plan",
        run_name_fn=generate_plan_langfuse_run_display_name,
        metadata=metadata,
        log_label="generate-plan",
    ) as span:
        yield span


@asynccontextmanager
async def generate_plan_langfuse_span_async(
    *,
    soothe_config: Any | None,
    goal_trace: Any | None,
    metadata: dict[str, Any] | None = None,
) -> AsyncIterator[Any | None]:
    """Async wrapper around :func:`generate_plan_langfuse_span` for station nodes."""
    with generate_plan_langfuse_span(
        soothe_config=soothe_config,
        goal_trace=goal_trace,
        metadata=metadata,
    ) as span:
        yield span
