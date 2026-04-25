"""Unified verbosity tier for event classification and message component visibility.

RFC-0024: Events and message components classify directly to a VerbosityTier,
which represents the minimum verbosity level at which content is visible.
"""

from __future__ import annotations

from enum import IntEnum

from soothe_sdk.core.types import VerbosityLevel


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


__all__ = [
    "VerbosityTier",
    "should_show",
]
