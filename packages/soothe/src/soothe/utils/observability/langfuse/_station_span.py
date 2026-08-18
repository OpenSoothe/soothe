"""Shared Langfuse parent spans for StrangeLoop plan stations.

``evaluate`` and ``generate_plan`` both pin planner LLM runs to the goal-loop
trace for the duration of the station node. The span is opened with
``start_as_current_observation`` so ambient OTEL context is active while the
planner runs; the planner's pinned handler still attaches generations to the
shared ``trace_id``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from soothe.utils.observability.langfuse._client import host_langfuse_client

logger = logging.getLogger(__name__)


def _trace_name(config: Any) -> str | None:
    try:
        return (config.observability.langfuse.trace_name or "").strip() or None
    except Exception:
        return None


def _start_station_observation(
    soothe_config: Any,
    *,
    goal_trace: Any,
    station: str,
    run_name: str,
    metadata: dict[str, Any] | None,
    include_trace_context: bool,
) -> Any:
    """Open a Langfuse span for a plan station; caller owns the context manager."""
    client = host_langfuse_client(soothe_config)
    kwargs: dict[str, Any] = {
        "as_type": "span",
        "name": run_name,
        "metadata": {
            "soothe_component": station,
            "soothe_station": station,
            **(metadata or {}),
        },
    }
    if include_trace_context:
        trace_id = getattr(goal_trace, "trace_id", None)
        if trace_id:
            kwargs["trace_context"] = {"trace_id": str(trace_id)}
    return client.start_as_current_observation(**kwargs)


@contextmanager
def station_langfuse_span(
    *,
    soothe_config: Any | None,
    goal_trace: Any | None,
    station: str,
    run_name_fn: Callable[[str | None], str],
    metadata: dict[str, Any] | None = None,
    log_label: str | None = None,
) -> Iterator[Any | None]:
    """Sync context manager: parent station span on the goal-loop trace.

    Yields the span when Langfuse is enabled, else ``None``. Failures are soft.
    """
    label = log_label or station
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

    run_name = run_name_fn(_trace_name(soothe_config))
    try:
        with _start_station_observation(
            soothe_config,
            goal_trace=goal_trace,
            station=station,
            run_name=run_name,
            metadata=metadata,
            include_trace_context=True,
        ) as span:
            yield span
    except TypeError:
        try:
            with _start_station_observation(
                soothe_config,
                goal_trace=goal_trace,
                station=station,
                run_name=run_name,
                metadata=metadata,
                include_trace_context=False,
            ) as span:
                yield span
        except Exception:
            logger.debug("[Plan] %s Langfuse span unavailable", label, exc_info=True)
            yield None
    except Exception:
        logger.debug("[Plan] %s Langfuse span unavailable", label, exc_info=True)
        yield None


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
    """Restore planner pinned trace id after a station completes."""
    if planner is None:
        return
    try:
        planner._pinned_trace_id = prior
    except Exception:
        logger.debug("[Plan] could not restore planner Langfuse trace pin", exc_info=True)


__all__ = [
    "bind_planner_langfuse_trace",
    "restore_planner_langfuse_trace",
    "station_langfuse_span",
]
