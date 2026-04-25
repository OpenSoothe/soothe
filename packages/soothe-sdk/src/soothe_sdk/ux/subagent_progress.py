"""Helper functions for subagent event processing.

This module provides utilities for CLI/TUI to extract subagent information
from capability event types.
"""

from __future__ import annotations


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
    "get_subagent_name_from_event",
]
