"""Shared essential event-type filtering for UX surfaces."""

from __future__ import annotations

from typing import Final

GOAL_START_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "soothe.cognition.agent_loop.started",
        "soothe.cognition.plan.creating",
    }
)

STEP_START_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "soothe.cognition.plan.step.started",
        "soothe.cognition.agent_loop.step.started",
    }
)

STEP_COMPLETE_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "soothe.cognition.plan.step.completed",
        "soothe.cognition.agent_loop.step.completed",
    }
)

LOOP_REASON_EVENT_TYPE: Final[str] = "soothe.cognition.agent_loop.reasoned"

ESSENTIAL_PROGRESS_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    set(GOAL_START_EVENT_TYPES)
    | set(STEP_START_EVENT_TYPES)
    | set(STEP_COMPLETE_EVENT_TYPES)
    | {LOOP_REASON_EVENT_TYPE}
)


def is_essential_progress_event_type(event_type: str) -> bool:
    """Return whether an event type is part of essential progress output."""
    return event_type in ESSENTIAL_PROGRESS_EVENT_TYPES


def is_goal_start_event_type(event_type: str) -> bool:
    """Return whether an event starts a goal header display."""
    return event_type in GOAL_START_EVENT_TYPES


def is_step_start_event_type(event_type: str) -> bool:
    """Return whether an event starts a step header display."""
    return event_type in STEP_START_EVENT_TYPES


def is_step_complete_event_type(event_type: str) -> bool:
    """Return whether an event marks step completion."""
    return event_type in STEP_COMPLETE_EVENT_TYPES


__all__ = [
    "ESSENTIAL_PROGRESS_EVENT_TYPES",
    "GOAL_START_EVENT_TYPES",
    "LOOP_REASON_EVENT_TYPE",
    "STEP_COMPLETE_EVENT_TYPES",
    "STEP_START_EVENT_TYPES",
    "is_essential_progress_event_type",
    "is_goal_start_event_type",
    "is_step_complete_event_type",
    "is_step_start_event_type",
]
