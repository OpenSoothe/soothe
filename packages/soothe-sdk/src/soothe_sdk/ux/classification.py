"""Event classification logic for UX display filtering.

Extracted from verbosity.py per RFC-610 (IG-185).
"""

from soothe_sdk.core.verbosity import VerbosityTier
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE, TOOL_CALL_UPDATES_BATCH


def _subagent_wire_tier(event_type: str) -> VerbosityTier | None:
    """Tier for curated ``soothe.subagent.*`` wire events (IG-339).

    All curated subagent wire signals (lifecycle and activity) are visible at NORMAL;
    verbosity only filters coarser domains — these are already sparse and metadata-only.
    """
    if not event_type.startswith("soothe.subagent."):
        return None
    return VerbosityTier.NORMAL


def classify_event_to_tier(event_type: str, namespace: tuple[str, ...] = ()) -> VerbosityTier:
    """Classify an event directly to a VerbosityTier.

    Uses the same domain-based defaults as the daemon's EventRegistry,
    matching the `_DOMAIN_DEFAULT_TIER` mapping from `event_catalog.py`.

    Args:
        event_type: The event type string (e.g., "soothe.cognition.agent_loop.started").
        namespace: Subagent namespace tuple (for non-soothe events).

    Returns:
        VerbosityTier for the event.

    Examples:
        >>> classify_event_to_tier("soothe.error.general.failed")
        <VerbosityTier.QUIET: 0>
        >>> classify_event_to_tier("soothe.output.telemetry.line")
        <VerbosityTier.QUIET: 0>
        >>> classify_event_to_tier("soothe.cognition.plan.creating")
        <VerbosityTier.NORMAL: 1>
    """
    # Stream tool wire (IG-416/427) — normal-tier progress for TUI tool/task rows.
    if event_type in (TOOL_CALL_UPDATES_BATCH, STREAM_TOOL_CALL_UPDATE):
        return VerbosityTier.NORMAL

    if event_type.startswith("soothe."):
        wire = _subagent_wire_tier(event_type)
        if wire is not None:
            return wire

        # Fine-grained overrides (RFC-0024 / UX tests — before coarse domain defaults)
        if event_type == "soothe.cognition.agent_loop.completed":
            return VerbosityTier.QUIET
        if "heartbeat" in event_type:
            return VerbosityTier.DEBUG
        segments = event_type.split(".")
        domain = segments[1] if len(segments) >= 2 else "unknown"
        return _DOMAIN_DEFAULT_TIER.get(domain, VerbosityTier.DEBUG)

    # Non-soothe events (from deepagents subagents) — not curated soothe.subagent.*
    if namespace or (".subagent." in event_type and not event_type.startswith("soothe.subagent.")):
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


__all__ = [
    "classify_event_to_tier",
]
