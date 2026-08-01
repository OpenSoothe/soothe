"""Langfuse parent span for the evaluate station (IG-672).

Wraps inventory + assess so LangChain planner generations nest under one
``evaluate`` observation on the goal-loop trace.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from soothe.utils.observability.langfuse._names import evaluate_langfuse_run_display_name

logger = logging.getLogger(__name__)


def _trace_name(config: Any) -> str | None:
    try:
        return (config.observability.langfuse.trace_name or "").strip() or None
    except Exception:
        return None


def _start_evaluate_observation(
    soothe_config: Any,
    *,
    goal_trace: Any,
    metadata: dict[str, Any] | None,
    include_trace_context: bool,
) -> Any:
    """Open a Langfuse span for evaluate; caller owns the context manager."""
    from langfuse import get_client
    from soothe_sdk.observability.langfuse._client import (
        ensure_langfuse_client,
        resolve_str,
    )

    ensure_langfuse_client(soothe_config)
    pub = resolve_str(soothe_config.observability.langfuse.public_key)
    client = get_client(public_key=pub) if pub else get_client()
    run_name = evaluate_langfuse_run_display_name(_trace_name(soothe_config))
    kwargs: dict[str, Any] = {
        "as_type": "span",
        "name": run_name,
        "metadata": {
            "soothe_component": "evaluate",
            "soothe_station": "evaluate",
            **(metadata or {}),
        },
    }
    if include_trace_context:
        trace_id = getattr(goal_trace, "trace_id", None)
        if trace_id:
            kwargs["trace_context"] = {"trace_id": str(trace_id)}
    return client.start_as_current_observation(**kwargs)


@contextmanager
def evaluate_langfuse_span(
    *,
    soothe_config: Any | None,
    goal_trace: Any | None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Any | None]:
    """Sync context manager: parent ``evaluate`` span on the goal-loop trace.

    Yields the span object when Langfuse is enabled, else ``None``. Failures are
    soft — evaluate must not abort when observability is unavailable.
    """
    if soothe_config is None or goal_trace is None:
        yield None
        return
    try:
        enabled = bool(getattr(goal_trace, "enabled", False))
        if not enabled or not soothe_config.observability.langfuse.enabled:
            yield None
            return
    except Exception:
        yield None
        return

    try:
        with _start_evaluate_observation(
            soothe_config,
            goal_trace=goal_trace,
            metadata=metadata,
            include_trace_context=True,
        ) as span:
            yield span
    except TypeError:
        # Older SDKs may not accept trace_context on start_as_current_observation.
        try:
            with _start_evaluate_observation(
                soothe_config,
                goal_trace=goal_trace,
                metadata=metadata,
                include_trace_context=False,
            ) as span:
                yield span
        except Exception:
            logger.debug("[Plan] evaluate Langfuse span unavailable", exc_info=True)
            yield None
    except Exception:
        logger.debug("[Plan] evaluate Langfuse span unavailable", exc_info=True)
        yield None


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


def bind_planner_langfuse_trace(planner: Any, goal_trace: Any | None) -> Any | None:
    """Pin planner LLM runs to the goal-loop trace; return prior pinned id."""
    if planner is None:
        return None
    prior = getattr(planner, "_pinned_trace_id", None)
    trace_id = getattr(goal_trace, "trace_id", None) if goal_trace is not None else None
    if trace_id:
        try:
            planner._pinned_trace_id = str(trace_id)
        except Exception:
            logger.debug("[Plan] could not pin planner Langfuse trace", exc_info=True)
    return prior


def restore_planner_langfuse_trace(planner: Any, prior: Any | None) -> None:
    """Restore planner pinned trace id after evaluate completes."""
    if planner is None:
        return
    try:
        planner._pinned_trace_id = prior
    except Exception:
        logger.debug("[Plan] could not restore planner Langfuse trace pin", exc_info=True)


__all__ = [
    "bind_planner_langfuse_trace",
    "evaluate_langfuse_span",
    "evaluate_langfuse_span_async",
    "restore_planner_langfuse_trace",
]
