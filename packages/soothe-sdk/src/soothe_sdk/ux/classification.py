"""Event classification logic for UX display filtering.

Extracted from verbosity.py.
"""

from soothe_sdk.core.verbosity import VerbosityTier
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE, TOOL_CALL_UPDATES_BATCH


def _subagent_wire_tier(event_type: str) -> VerbosityTier | None:
    """Tier for curated ``soothe.subagent.*`` wire events.

    All curated subagent wire signals (lifecycle and activity) are visible at NORMAL;
    verbosity only filters coarser domains — these are already sparse and metadata-only.
    """
    if not event_type.startswith("soothe.subagent."):
        return None
    return VerbosityTier.NORMAL


def classify_event_to_tier(event_type: str, namespace: tuple[str, ...] = ()) -> VerbosityTier:
    """Classify an event directly to a VerbosityTier.

    Uses the same domain-based defaults as the server's EventRegistry,
    matching the `_DOMAIN_DEFAULT_TIER` mapping from `event_catalog.py`.

    Args:
        event_type: The event type string (e.g., "soothe.cognition.strange_loop.started").
        namespace: Subagent namespace tuple (for non-soothe events).

    Returns:
        VerbosityTier for the event — NORMAL (client-visible) or INTERNAL (hidden).

    Examples:
        >>> classify_event_to_tier("soothe.error.general.failed")
        <VerbosityTier.NORMAL: 1>
        >>> classify_event_to_tier("soothe.cognition.plan.creating")
        <VerbosityTier.NORMAL: 1>
        >>> classify_event_to_tier("soothe.internal.iteration.started")
        <VerbosityTier.INTERNAL: 99>
    """
    # Stream tool wire — client-visible progress for TUI tool/task rows.
    if event_type in (TOOL_CALL_UPDATES_BATCH, STREAM_TOOL_CALL_UPDATE):
        return VerbosityTier.NORMAL

    if event_type.startswith("soothe."):
        wire = _subagent_wire_tier(event_type)
        if wire is not None:
            return wire

        if "heartbeat" in event_type:
            return VerbosityTier.INTERNAL
        segments = event_type.split(".")
        domain = segments[1] if len(segments) >= 2 else "unknown"
        return _DOMAIN_DEFAULT_TIER.get(domain, VerbosityTier.INTERNAL)

    # Non-soothe events (from subagents not under curated soothe.subagent.*) and
    # thinking/heartbeat traces are internal-only.
    return VerbosityTier.INTERNAL


# Domain-based default verbosity tiers, matching server's EventRegistry.
# Kept in sync with the server's event catalog domain default tiers.
_DOMAIN_DEFAULT_TIER: dict[str, VerbosityTier] = {
    "lifecycle": VerbosityTier.INTERNAL,
    "protocol": VerbosityTier.INTERNAL,
    "cognition": VerbosityTier.NORMAL,
    "loop": VerbosityTier.NORMAL,  # Loop relay events (clarification)
    "tool": VerbosityTier.INTERNAL,  # Tool display via LangChain on_tool_call
    "subagent": VerbosityTier.INTERNAL,
    "output": VerbosityTier.NORMAL,
    "error": VerbosityTier.NORMAL,
    "agentic": VerbosityTier.NORMAL,
}


__all__ = [
    "classify_event_to_tier",
]
