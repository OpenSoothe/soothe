"""Progress event rendering for CLI output.

This module provides simple progress event rendering to stderr.
Refactored for RFC-0019 unified event processing.
Refactored for RFC-0020 registry-driven display.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any

from soothe.core.event_catalog import (
    GOAL_BATCH_STARTED,
    ITERATION_COMPLETED,
    ITERATION_STARTED,
    PLAN_CREATED,
    PLAN_REFLECTED,
)
from soothe.ux.core.event_filter import should_skip_event
from soothe.ux.core.event_formatter import build_event_summary, truncate_summary

if TYPE_CHECKING:
    from soothe.protocols.planner import Plan

logger = logging.getLogger(__name__)

# Event type to human-readable label mapping
_EVENT_LABELS: dict[str, str] = {
    PLAN_CREATED: "plan",
    PLAN_REFLECTED: "reflect",
    GOAL_BATCH_STARTED: "goals",
    ITERATION_STARTED: "iteration",
    ITERATION_COMPLETED: "iteration",
}


def render_progress_event(
    event_type: str,
    data: dict[str, Any],
    *,
    prefix: str | None = None,
    current_plan: Plan | None = None,
) -> None:
    """Render a soothe.* event using registry template with fallback to hardcoded logic.

    Args:
        event_type: Event type string.
        data: Event dict with 'type' key.
        prefix: Optional prefix for subagent namespace.
        current_plan: Current plan for status display.
    """
    if not event_type:
        event_type = data.get("type", "")
    if not event_type:
        return

    # Skip batch/step/policy events (handled by renderer's plan update mechanism, or not rendered)
    if should_skip_event(event_type):
        return

    # RFC-0020 three-level tree for agentic events
    if event_type.startswith("soothe.agentic."):
        _render_agentic_event(event_type, data)
        return

    # Try registry first (RFC-0020 Principle 1: Registry-Driven Display)
    summary = build_event_summary(event_type, data)
    if summary:
        summary = truncate_summary(summary)
        prefix_str = f"[{prefix}] " if prefix else ""
        label = _get_event_label(event_type)
        line = f"{prefix_str}[{label}] {summary}\n"
        sys.stderr.write(line)
        sys.stderr.flush()
        return

    # Fallback to hardcoded summary for special cases (backward compatibility)
    summary = _build_summary(event_type, data, current_plan)
    if not summary:
        return

    # Format output line
    prefix_str = f"[{prefix}] " if prefix else ""
    label = _get_event_label(event_type)
    line = f"{prefix_str}[{label}] {summary}\n"

    sys.stderr.write(line)
    sys.stderr.flush()


def _render_agentic_event(event_type: str, data: dict[str, Any]) -> None:
    """Render agentic loop events as three-level tree (RFC-0020).

    Level 1: Goal summary (●)
    Level 2: Step description (└)
    Level 3: Step result (└ ✓)

    Args:
        event_type: Event type string.
        data: Event payload.
    """
    if "loop.started" in event_type:
        # Level 1: Goal summary
        goal = data.get("goal", "")
        if goal:
            sys.stderr.write(f"\n● {goal}\n")
            sys.stderr.flush()

    elif "step.started" in event_type:
        # Level 2: Step description
        description = data.get("description", "")
        if description:
            sys.stderr.write(f"  └ {description}\n")
            sys.stderr.flush()

    elif "step.completed" in event_type:
        # Level 3: Step result
        success = data.get("success", False)
        summary = data.get("summary", "Done")
        duration_ms = data.get("duration_ms", 0)
        icon = "✓" if success else "✗"
        result_line = f"     └ {icon} {summary}"
        if duration_ms > 0:
            # Format duration nicely
            if duration_ms >= 1000:  # noqa: PLR2004
                result_line += f" ({duration_ms / 1000:.1f}s)"
            else:
                result_line += f" ({duration_ms}ms)"
        sys.stderr.write(result_line + "\n")
        sys.stderr.flush()

    elif "loop.completed" in event_type:
        # Level 1: Goal conclusion
        evidence = data.get("evidence_summary", "")
        if evidence:
            # Truncate evidence for clean display
            evidence = truncate_summary(evidence, max_len=80)
            sys.stderr.write(f"\n● Done: {evidence}\n")
            sys.stderr.flush()


def _get_event_label(event_type: str) -> str:
    """Get human-readable label for event type.

    Args:
        event_type: Event type string.

    Returns:
        Human-readable label.
    """
    # Check hardcoded labels first
    if event_type in _EVENT_LABELS:
        return _EVENT_LABELS[event_type]

    # Extract domain from event type
    segments = event_type.split(".")
    if len(segments) >= 2:  # noqa: PLR2004
        domain = segments[1]
        if domain == "subagent" and len(segments) >= 3:  # noqa: PLR2004
            return segments[2]  # e.g., "browser", "claude"
        return domain

    return "event"


def _build_summary(event_type: str, data: dict[str, Any], _current_plan: Plan | None = None) -> str:
    """Build human-readable summary for an event.

    Args:
        event_type: Event type string.
        data: Event payload.
        current_plan: Current plan for status display.

    Returns:
        Summary string or empty.
    """
    if event_type == PLAN_CREATED:
        # Show full goal and all steps in a tree
        goal = data.get("goal", "")
        steps = data.get("steps", [])
        reasoning = data.get("reasoning")
        lines = [f"● {goal} ({len(steps)} steps)"]
        # Show reasoning if present
        if reasoning:
            lines.append(f"  Reasoning: {reasoning}")
        # Show all steps as a tree
        for step in steps:
            step_id = step.get("id", "?")
            desc = step.get("description", "")
            lines.append(f"  ├ {step_id}: {desc}")
        return "\n".join(lines)

    # Batch/step/policy events are skipped via should_skip_event() above
    # No hardcoded fallback needed - handled by renderer or not rendered

    if event_type == PLAN_REFLECTED:
        assessment = data.get("assessment", "")
        should_revise = data.get("should_revise", False)
        status = "needs revision" if should_revise else "complete"
        # Show full assessment, no truncation
        brief = f"{status}: {assessment}" if assessment else status
        return f"○ Reflection: {brief}"

    if event_type == GOAL_BATCH_STARTED:
        goals = data.get("goal_indices", [])
        return f"┬ Starting goals: {goals}"

    if event_type == ITERATION_STARTED:
        iteration = data.get("iteration", 0)
        return f"├ Iteration {iteration + 1}"

    if event_type == ITERATION_COMPLETED:
        iteration = data.get("iteration", 0)
        return f"└ Iteration {iteration + 1} done"

    # Research subagent events now use registry templates (RFC-0020)
    # Removed hardcoded research logic - events have proper summary_template registrations

    return ""
