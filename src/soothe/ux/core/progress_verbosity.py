"""Progress verbosity classification and filtering helpers.

RFC-0015: Classification uses the structural domain tier
(``event_type.split('.')[1]``) from the event catalog registry.
"""

from __future__ import annotations

from typing import Any, Literal

from soothe.ux.core.display_policy import VerbosityLevel

ProgressCategory = Literal[
    "assistant_text",
    "protocol",
    "subagent_progress",
    "subagent_custom",
    "tool_activity",
    "thinking",
    "error",
    "debug",
    "internal",  # Internal events - NEVER shown at any verbosity level
]


def classify_custom_event(namespace: tuple[Any, ...], data: dict[str, Any]) -> ProgressCategory:
    """Classify a custom event into a verbosity category.

    Uses the RFC-0015 domain tier (second segment) for structural
    classification. Falls back to heuristics for non-soothe events.

    For soothe.* events, queries the event registry for verbosity mapping.
    """
    etype = str(data.get("type", ""))

    if not etype.startswith("soothe."):
        if namespace:
            if "thinking" in etype or "heartbeat" in etype:
                return "thinking"
            return "subagent_custom"
        if "thinking" in etype or "heartbeat" in etype:
            return "thinking"
        return "debug"

    # Try registry first for soothe.* events (RFC-0015)
    from soothe.core.event_catalog import REGISTRY

    meta = REGISTRY.get_meta(etype)
    if meta and meta.verbosity:
        # Map registry verbosity to ProgressCategory
        verbosity_map: dict[str, ProgressCategory] = {
            "minimal": "protocol",
            "normal": "protocol",
            "detailed": "protocol",
            "subagent_progress": "subagent_progress",
            "subagent_custom": "subagent_custom",
            "tool_activity": "tool_activity",
            "error": "error",
            "debug": "debug",
            "protocol": "protocol",
            "assistant_text": "assistant_text",
        }
        return verbosity_map.get(meta.verbosity, "protocol")

    # Fallback to structural classification
    segments = etype.split(".")
    domain = segments[1] if len(segments) >= 2 else "unknown"  # noqa: PLR2004

    if domain == "error":
        return "error"
    if domain == "output":
        return "assistant_text"
    if domain == "tool":
        return "protocol"
    if domain == "subagent":
        if "thinking" in etype or "heartbeat" in etype:
            return "thinking"
        if etype.endswith((".text", ".response", ".result")):
            return "protocol"
        return "subagent_custom"
    if domain in ("lifecycle", "protocol"):
        return "protocol"

    if "thinking" in etype or "heartbeat" in etype:
        return "thinking"
    return "protocol"


def should_show(category: ProgressCategory, verbosity: VerbosityLevel) -> bool:
    """Return whether a progress category is visible at the given verbosity."""
    # Internal category is NEVER shown at any verbosity level
    if category == "internal":
        return False
    if verbosity == "debug":
        return True
    if verbosity == "detailed":
        return category in {
            "assistant_text",
            "protocol",
            "subagent_progress",
            "subagent_custom",
            "tool_activity",
            "error",
        }
    if verbosity == "normal":
        return category in {"assistant_text", "protocol", "subagent_progress", "error"}
    return category in {"assistant_text", "error"}
