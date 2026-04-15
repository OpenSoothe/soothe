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

    Uses the same domain-based defaults as the daemon's EventRegistry,
    matching the ``_DOMAIN_DEFAULT_TIER`` mapping from ``event_catalog.py``.

    Args:
        event_type: The event type string (e.g., "soothe.cognition.agent_loop.started").
        namespace: Subagent namespace tuple (for non-soothe events).

    Returns:
        VerbosityTier for the event.

    Examples:
        >>> classify_event_to_tier("soothe.error.general.failed")
        <VerbosityTier.QUIET: 0>
        >>> classify_event_to_tier("soothe.output.chitchat.responding")
        <VerbosityTier.QUIET: 0>
        >>> classify_event_to_tier("soothe.cognition.plan.creating")
        <VerbosityTier.NORMAL: 1>
    """
    if event_type.startswith("soothe."):
        segments = event_type.split(".")
        domain = segments[1] if len(segments) >= 2 else "unknown"
        return _DOMAIN_DEFAULT_TIER.get(domain, VerbosityTier.DEBUG)

    # Non-soothe events (from deepagents subagents)
    if namespace or ".subagent." in event_type:
        return VerbosityTier.DETAILED

    # Thinking and heartbeats are debug-level
    if "thinking" in event_type or "heartbeat" in event_type:
        return VerbosityTier.DEBUG

    # Fallback to DEBUG
    return VerbosityTier.DEBUG


# Domain-based default verbosity tiers, matching daemon's EventRegistry.
# Kept in sync with soothe.core.event_catalog._DOMAIN_DEFAULT_TIER.
_DOMAIN_DEFAULT_TIER: dict[str, VerbosityTier] = {
    "lifecycle": VerbosityTier.DETAILED,
    "protocol": VerbosityTier.DETAILED,
    "cognition": VerbosityTier.NORMAL,
    "tool": VerbosityTier.INTERNAL,  # Tool display via LangChain on_tool_call
    "subagent": VerbosityTier.DETAILED,
    "output": VerbosityTier.QUIET,
    "error": VerbosityTier.QUIET,
    "agentic": VerbosityTier.NORMAL,
}


# Backward compatibility alias
ProgressCategory = VerbosityTier


__all__ = [
    "ProgressCategory",
    "VerbosityLevel",
    "VerbosityTier",
    "classify_event_to_tier",
    "should_show",
]
