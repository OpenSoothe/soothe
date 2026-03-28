"""Shared event filtering logic for CLI and TUI modes.

Defines which events should be rendered vs skipped.
"""

from __future__ import annotations

from soothe.core.event_catalog import (
    PLAN_BATCH_STARTED,
    PLAN_STEP_COMPLETED,
    PLAN_STEP_FAILED,
    PLAN_STEP_STARTED,
    POLICY_CHECKED,
    POLICY_DENIED,
)

# Events to skip in both CLI and TUI (unified behavior)
SKIP_EVENTS = {
    # Plan events handled by renderer's plan update mechanism
    PLAN_BATCH_STARTED,
    PLAN_STEP_STARTED,
    PLAN_STEP_COMPLETED,
    PLAN_STEP_FAILED,
    # Policy events not rendered (RFC-0019)
    POLICY_CHECKED,
    POLICY_DENIED,
}


def should_skip_event(event_type: str) -> bool:
    """Check if event should be skipped from rendering.

    Args:
        event_type: Event type string.

    Returns:
        True if event should be skipped.
    """
    return event_type in SKIP_EVENTS


__all__ = [
    "SKIP_EVENTS",
    "should_skip_event",
]
