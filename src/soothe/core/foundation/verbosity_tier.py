"""Unified verbosity tier for event classification and message component visibility.

RFC-0024: Events and message components classify directly to a VerbosityTier,
which represents the minimum verbosity level at which content is visible.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Literal

VerbosityLevel = Literal["quiet", "minimal", "normal", "detailed", "debug"]
"""User-configured verbosity level for filtering display content.

`minimal` is accepted as a compatibility alias for `normal`.
"""


class VerbosityTier(IntEnum):
    """Minimum verbosity level at which content is visible.

    Values are ordered so comparison works: tier <= verbosity means visible.

    Usage:
        >>> should_show(VerbosityTier.NORMAL, "normal")
        True
        >>> should_show(VerbosityTier.DETAILED, "normal")
        False
    """

    QUIET = 0  # Always visible (errors, assistant text, final reports)
    NORMAL = 1  # Standard progress (plan updates, milestones, agentic loop)
    DETAILED = 2  # Detailed internals (protocol events, tool calls, subagent activity)
    DEBUG = 3  # Everything including internals (thinking, heartbeats)
    INTERNAL = 99  # Never shown at any level (implementation details)


_VERBOSITY_LEVEL_VALUES: dict[VerbosityLevel, int] = {
    "quiet": 0,
    "minimal": 1,
    "normal": 1,
    "detailed": 2,
    "debug": 3,
}


def should_show(tier: VerbosityTier, verbosity: VerbosityLevel) -> bool:
    """Return True if tier is visible at the given verbosity.

    Args:
        tier: The minimum verbosity level for this content.
        verbosity: User's current verbosity setting.

    Returns:
        True if content should be displayed.

    Examples:
        >>> should_show(VerbosityTier.QUIET, "quiet")
        True
        >>> should_show(VerbosityTier.NORMAL, "quiet")
        False
        >>> should_show(VerbosityTier.NORMAL, "normal")
        True
        >>> should_show(VerbosityTier.INTERNAL, "debug")
        False
    """
    if tier == VerbosityTier.INTERNAL:
        return False
    return tier <= _VERBOSITY_LEVEL_VALUES[verbosity]


def classify_event_to_tier(event_type: str, namespace: tuple[str, ...] = ()) -> VerbosityTier:
    """Classify an event directly to a VerbosityTier.

    For soothe.* events, queries the event registry for the registered tier.
    For non-soothe events (from subagents like deepagents), uses heuristics.

    Args:
        event_type: The event type string (e.g., "soothe.agentic.loop.started").
        namespace: Subagent namespace tuple (for non-soothe events).

    Returns:
        VerbosityTier for the event.

    Examples:
        >>> classify_event_to_tier("soothe.agentic.loop.started")
        <VerbosityTier.NORMAL: 1>
        >>> classify_event_to_tier("soothe.error.general")
        <VerbosityTier.QUIET: 0>
        >>> classify_event_to_tier("thinking.heartbeat", namespace=())
        <VerbosityTier.DEBUG: 3>
    """
    from soothe.core.event_catalog import REGISTRY

    if event_type.startswith("soothe."):
        return REGISTRY.get_verbosity(event_type)

    if namespace:
        if "thinking" in event_type or "heartbeat" in event_type:
            return VerbosityTier.DEBUG
        return VerbosityTier.DETAILED

    if "thinking" in event_type or "heartbeat" in event_type:
        return VerbosityTier.DEBUG
    return VerbosityTier.DEBUG


# Backward compatibility alias
ProgressCategory = VerbosityTier


def classify_custom_event(namespace: tuple, data: dict) -> VerbosityTier:
    """Deprecated: Use `classify_event_to_tier` instead."""
    event_type = str(data.get("type", ""))
    return classify_event_to_tier(event_type, namespace)


__all__ = [
    "ProgressCategory",
    "VerbosityLevel",
    "VerbosityTier",
    "classify_custom_event",
    "classify_event_to_tier",
    "should_show",
]
