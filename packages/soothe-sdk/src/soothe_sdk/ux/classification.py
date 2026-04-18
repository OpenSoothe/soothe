"""Event classification logic for UX display filtering.

Extracted from verbosity.py per RFC-610 (IG-185).
"""

from soothe_sdk.ux.subagent_progress import is_subagent_progress_event
from soothe_sdk.verbosity import VerbosityTier


def _is_legacy_subagent_milestone_event(event_type: str) -> bool:
    """Return True for legacy ``soothe.subagent.*`` lifecycle events (NORMAL tier)."""
    if not event_type.startswith("soothe.subagent."):
        return False
    if ".dispatched" in event_type or ".judgement" in event_type:
        return True
    # Subagent run completed (avoid matching ``*.step.*`` granular completions)
    if event_type.endswith(".completed") and ".step." not in event_type:
        return True
    return False


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
        >>> classify_event_to_tier("soothe.output.chitchat.responded")
        <VerbosityTier.QUIET: 0>
        >>> classify_event_to_tier("soothe.cognition.plan.creating")
        <VerbosityTier.NORMAL: 1>
    """
    if event_type.startswith("soothe."):
        # RFC-210 capability events — align with StreamDisplayPipeline (IG-192, IG-195)
        if event_type.startswith("soothe.capability."):
            if is_subagent_progress_event(event_type):
                return VerbosityTier.NORMAL
            return VerbosityTier.DETAILED

        if _is_legacy_subagent_milestone_event(event_type):
            return VerbosityTier.NORMAL

        # Fine-grained overrides (RFC-0024 / UX tests — before coarse domain defaults)
        if event_type == "soothe.cognition.agent_loop.completed":
            return VerbosityTier.QUIET
        if "heartbeat" in event_type:
            return VerbosityTier.DEBUG
        if event_type == "soothe.output.chitchat.started":
            return VerbosityTier.INTERNAL

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


__all__ = [
    "classify_event_to_tier",
]
