"""Progress event rendering for CLI output.

This module provides simple progress event rendering to stderr.
Refactored for RFC-0019 unified event processing.
"""

from __future__ import annotations

import sys
from typing import Any

from soothe.core.event_catalog import (
    GOAL_BATCH_STARTED,
    ITERATION_COMPLETED,
    ITERATION_STARTED,
    PLAN_BATCH_STARTED,
    PLAN_CREATED,
    PLAN_REFLECTED,
    PLAN_STEP_COMPLETED,
    PLAN_STEP_FAILED,
    PLAN_STEP_STARTED,
)

# Event type to human-readable label mapping
_EVENT_LABELS: dict[str, str] = {
    PLAN_CREATED: "plan",
    PLAN_BATCH_STARTED: "batch",
    PLAN_STEP_STARTED: "step",
    PLAN_STEP_COMPLETED: "step",
    PLAN_STEP_FAILED: "step",
    PLAN_REFLECTED: "reflect",
    GOAL_BATCH_STARTED: "goals",
    ITERATION_STARTED: "iteration",
    ITERATION_COMPLETED: "iteration",
}

# Max number of step IDs to display in batch summary
_MAX_BATCH_IDS_DISPLAY = 3


def render_progress_event(
    data: dict[str, Any],
    *,
    prefix: str | None = None,
) -> None:
    """Render a soothe.* event as a structured progress line to stderr.

    Args:
        data: Event dict with 'type' key.
        prefix: Optional prefix for subagent namespace.
    """
    event_type = data.get("type", "")
    if not event_type:
        return

    # Get label for event type
    label = _EVENT_LABELS.get(event_type, "event")
    if not label:
        return

    # Build summary based on event type
    summary = _build_summary(event_type, data)
    if not summary:
        return

    # Format output line
    prefix_str = f"[{prefix}] " if prefix else ""
    line = f"{prefix_str}[{label}] {summary}\n"

    sys.stderr.write(line)
    sys.stderr.flush()


def _build_summary(event_type: str, data: dict[str, Any]) -> str:
    """Build human-readable summary for an event.

    Args:
        event_type: Event type string.
        data: Event payload.

    Returns:
        Summary string or empty.
    """
    if event_type == PLAN_CREATED:
        goal = data.get("goal", "")[:60]
        steps = len(data.get("steps", []))
        return f"● {goal} ({steps} steps)"

    if event_type == PLAN_BATCH_STARTED:
        batch_ids = data.get("step_ids", [])
        shown = batch_ids[:_MAX_BATCH_IDS_DISPLAY]
        suffix = "..." if len(batch_ids) > _MAX_BATCH_IDS_DISPLAY else ""
        return f"┬ Starting batch: {', '.join(str(s) for s in shown)}{suffix}"

    if event_type == PLAN_STEP_STARTED:
        step_id = data.get("step_id", "?")
        desc = data.get("description", "")[:50]
        return f"├ {step_id}: {desc}"

    if event_type == PLAN_STEP_COMPLETED:
        step_id = data.get("step_id", "?")
        success = data.get("success", True)
        duration = data.get("duration_ms", 0)
        icon = "✓" if success else "✗"
        dur_str = f" ({duration}ms)" if duration else ""
        return f"├ {step_id} {icon}{dur_str}"

    if event_type == PLAN_STEP_FAILED:
        step_id = data.get("step_id", "?")
        error = data.get("error", "")[:40]
        blocked = data.get("blocked_steps", [])
        blocked_str = f" (blocked: {blocked})" if blocked else ""
        return f"├ {step_id} ✗ {error}{blocked_str}"

    if event_type == PLAN_REFLECTED:
        status = data.get("status", "unknown")
        return f"○ Reflection: {status}"

    if event_type == GOAL_BATCH_STARTED:
        goals = data.get("goal_indices", [])
        return f"┬ Starting goals: {goals}"

    if event_type == ITERATION_STARTED:
        iteration = data.get("iteration", 0)
        return f"├ Iteration {iteration + 1}"

    if event_type == ITERATION_COMPLETED:
        iteration = data.get("iteration", 0)
        return f"└ Iteration {iteration + 1} done"

    return ""
