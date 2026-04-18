"""Helper functions for identifying important subagent progress events.

This module provides utilities for CLI/TUI to identify which subagent events
are important for progress tracking (visible at NORMAL verbosity tier).

Usage:
    from soothe_sdk.ux import is_subagent_progress_event

    if is_subagent_progress_event(event_type):
        # Render as important progress indicator
        render_progress_event(event_type, data)
"""

from __future__ import annotations

from typing import Final

# Important subagent progress events (NORMAL tier - visible by default)
# These are the key lifecycle and milestone events that users want to see
SUBAGENT_PROGRESS_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        # Browser subagent lifecycle
        "soothe.capability.browser.started",
        "soothe.capability.browser.completed",
        # Claude subagent lifecycle (dispatch + completion visible)
        "soothe.capability.claude.started",
        "soothe.capability.claude.completed",
        # Research subagent lifecycle and meaningful progress
        "soothe.capability.research.started",
        "soothe.capability.research.completed",
        "soothe.capability.research.judgement.reporting",  # LLM decision reasoning
    }
)


def is_subagent_progress_event(event_type: str) -> bool:
    """Check if event is an important subagent progress indicator.

    Important events are those visible at NORMAL verbosity tier, representing
    key lifecycle moments (started/completed) or meaningful progress updates
    (like research judgement decisions).

    Args:
        event_type: Full event type string (e.g., "soothe.capability.browser.started").

    Returns:
        True if this is an important progress event that should be prominently displayed.

    Example:
        >>> is_subagent_progress_event("soothe.capability.browser.started")
        True
        >>> is_subagent_progress_event("soothe.capability.browser.step.running")
        False  # DETAILED tier - internal step
        >>> is_subagent_progress_event("soothe.capability.research.judgement.reporting")
        True  # Meaningful progress at NORMAL tier
    """
    return event_type in SUBAGENT_PROGRESS_EVENT_TYPES


def get_subagent_name_from_event(event_type: str) -> str | None:
    """Extract subagent name from capability event type.

    Args:
        event_type: Full event type string.

    Returns:
        Subagent name (e.g., "browser", "claude", "research") or None if not a capability event.

    Example:
        >>> get_subagent_name_from_event("soothe.capability.browser.started")
        'browser'
        >>> get_subagent_name_from_event("soothe.cognition.plan.created")
        None
    """
    if not event_type.startswith("soothe.capability."):
        return None

    parts = event_type.split(".")
    if len(parts) >= 3:
        return parts[2]  # "soothe.capability.<subagent>.<action>"
    return None


__all__ = [
    "SUBAGENT_PROGRESS_EVENT_TYPES",
    "is_subagent_progress_event",
    "get_subagent_name_from_event",
]
