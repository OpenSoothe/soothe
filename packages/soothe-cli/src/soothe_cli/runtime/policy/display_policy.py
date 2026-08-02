"""Unified Display Policy Module for CLI and TUI.

This module centralizes all event filtering, content processing, and display
policy decisions in one place. Both CLI and TUI renderers use this policy
to determine:

1. Which events to show/hide (fixed “normal”-equivalent gating, IG-343)
2. Which message types are internal vs user-facing
4. How to handle different event categories

Design Principles:
- Event-based filtering over content-based filtering
- Explicit policy rules over implicit pattern matching
- Centralized configuration for consistency
- Easy to extend without modifying multiple files

Usage:
    from soothe_cli.runtime.policy.display_policy import DisplayPolicy

    policy = DisplayPolicy()

    if policy.should_show_event(event_type, data):
        render_event(data)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soothe_sdk.core.verbosity import VerbosityTier, should_show
from soothe_sdk.ux import classify_event_to_tier

# =============================================================================
# Policy Configuration Constants
# =============================================================================

# Event types that should NEVER be shown (internal implementation details)
INTERNAL_EVENT_TYPES: frozenset[str] = frozenset()

# Event types to skip in progress display (handled by plan update mechanism or not rendered).
SKIP_EVENT_TYPES: frozenset[str] = frozenset()

# =============================================================================
# Display Policy Class
# =============================================================================


@dataclass
class DisplayPolicy:
    """Unified display policy for CLI and TUI.

    This class centralizes all decisions about what to show/hide
    and how to process events for display.

    Event visibility uses a single fixed ceiling equivalent to the former **normal** mode (IG-343).
    """

    # ==========================================================================
    # Event Filtering
    # ==========================================================================

    def should_show_event(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,  # noqa: ARG002
        namespace: tuple[str, ...] = (),
    ) -> bool:
        """Determine if an event should be displayed.

        Args:
            event_type: The event type string (e.g., "soothe.tool.research.analyze")
            data: Optional event data dict
            namespace: Subagent namespace tuple

        Returns:
            True if the event should be shown, False otherwise
        """
        # Internal events are NEVER shown
        if event_type in INTERNAL_EVENT_TYPES:
            return False

        # Skip certain event types (handled by plan update mechanism)
        if event_type in SKIP_EVENT_TYPES:
            return False

        tier = self._classify_event(event_type, namespace)
        return self._should_show_tier(tier)

    def _classify_event(
        self,
        event_type: str,
        namespace: tuple[str, ...] = (),
    ) -> VerbosityTier:
        """Classify an event directly to a VerbosityTier."""
        return classify_event_to_tier(event_type, namespace)

    def _should_show_tier(self, tier: VerbosityTier) -> bool:
        """Check if a tier should be shown (fixed normal-equivalent gating)."""
        return should_show(tier, "normal")


__all__ = [
    "INTERNAL_EVENT_TYPES",
    "SKIP_EVENT_TYPES",
    "DisplayPolicy",
    "VerbosityTier",
]
