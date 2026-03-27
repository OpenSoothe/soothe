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
    PLAN_BATCH_STARTED,
    PLAN_CREATED,
    PLAN_REFLECTED,
    PLAN_STEP_COMPLETED,
    PLAN_STEP_FAILED,
    PLAN_STEP_STARTED,
    REGISTRY,
)
from soothe.subagents.research.events import (
    TOOL_RESEARCH_ANALYZE,
    TOOL_RESEARCH_COMPLETED,
    TOOL_RESEARCH_GATHER,
    TOOL_RESEARCH_GATHER_DONE,
    TOOL_RESEARCH_QUERIES_GENERATED,
    TOOL_RESEARCH_REFLECT,
    TOOL_RESEARCH_REFLECTION_DONE,
    TOOL_RESEARCH_SUB_QUESTIONS,
    TOOL_RESEARCH_SUMMARIZE,
    TOOL_RESEARCH_SYNTHESIZE,
)

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
    # Research tool events
    TOOL_RESEARCH_ANALYZE: "research",
    TOOL_RESEARCH_SUB_QUESTIONS: "research",
    TOOL_RESEARCH_QUERIES_GENERATED: "research",
    TOOL_RESEARCH_GATHER: "research",
    TOOL_RESEARCH_GATHER_DONE: "research",
    TOOL_RESEARCH_SUMMARIZE: "research",
    TOOL_RESEARCH_REFLECT: "research",
    TOOL_RESEARCH_REFLECTION_DONE: "research",
    TOOL_RESEARCH_SYNTHESIZE: "research",
    TOOL_RESEARCH_COMPLETED: "research",
}

# Events to skip (handled by renderer's plan update mechanism)
_SKIP_EVENTS = {
    PLAN_BATCH_STARTED,
    PLAN_STEP_STARTED,
    PLAN_STEP_COMPLETED,
    PLAN_STEP_FAILED,
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

    # Skip batch/step events (handled by renderer's plan update mechanism)
    if event_type in _SKIP_EVENTS:
        return

    # This is a simplified renderer - only handle whitelisted events
    # Policy events and other events are handled elsewhere
    if event_type not in _EVENT_LABELS:
        return

    # Try registry first (RFC-0020 Principle 1: Registry-Driven Display)
    meta = REGISTRY.get_meta(event_type)
    if meta and meta.summary_template:
        try:
            summary = meta.summary_template.format(**data)
        except (KeyError, ValueError) as e:
            logger.debug("Failed to format template for %s: %s", event_type, e)
            # Fall through to hardcoded logic
        else:
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
        lines = [f"● {goal} ({len(steps)} steps)"]
        # Show all steps as a tree
        for step in steps:
            step_id = step.get("id", "?")
            desc = step.get("description", "")
            lines.append(f"  ├ {step_id}: {desc}")
        return "\n".join(lines)

    # Batch and step events are now skipped (handled by renderer)
    # Keeping this for backwards compatibility if called directly
    if event_type == PLAN_BATCH_STARTED:
        return ""

    if event_type == PLAN_STEP_STARTED:
        return ""

    if event_type == PLAN_STEP_COMPLETED:
        return ""

    if event_type == PLAN_STEP_FAILED:
        return ""

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

    # Research tool events
    if event_type == TOOL_RESEARCH_ANALYZE:
        topic = data.get("topic", "")
        return f"● Research: {topic}"

    if event_type == TOOL_RESEARCH_SUB_QUESTIONS:
        sub_questions = data.get("sub_questions", [])
        count = data.get("count", len(sub_questions))
        if sub_questions:
            # Show subquestions as a tree
            lines = [f"├ Sub-questions ({count}):"]
            for sq in sub_questions:
                q = sq.get("question", str(sq)) if isinstance(sq, dict) else str(sq)
                lines.append(f"  ├ {q}")
            return "\n".join(lines)
        return f"├ Identified {count} sub-questions"

    if event_type == TOOL_RESEARCH_QUERIES_GENERATED:
        queries = data.get("queries", [])
        if queries:
            lines = [f"├ Generated queries ({len(queries)}):"]
            for q in queries:
                lines.append(f"  ├ {q}")
            return "\n".join(lines)
        return ""

    if event_type == TOOL_RESEARCH_GATHER:
        query = data.get("query", "")
        domain = data.get("domain", "")
        return f"├ Gathering from {domain}: {query}"

    if event_type == TOOL_RESEARCH_GATHER_DONE:
        result_count = data.get("result_count", 0)
        return f"  └ Gathered {result_count} results"

    if event_type == TOOL_RESEARCH_SUMMARIZE:
        total = data.get("total_summaries", 0)
        return f"├ Summarizing {total} results"

    if event_type == TOOL_RESEARCH_REFLECT:
        loop = data.get("loop", 0)
        return f"├ Reflecting (loop {loop + 1})"

    if event_type == TOOL_RESEARCH_REFLECTION_DONE:
        is_sufficient = data.get("is_sufficient", False)
        follow_up = data.get("follow_up_count", 0)
        status = "✓ sufficient" if is_sufficient else f"needs {follow_up} follow-ups"
        return f"  └ Reflection: {status}"

    if event_type == TOOL_RESEARCH_SYNTHESIZE:
        return "├ Synthesizing findings"

    if event_type == TOOL_RESEARCH_COMPLETED:
        answer_length = data.get("answer_length", 0)
        return f"└ Research completed ({answer_length} chars)"

    return ""
