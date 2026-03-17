"""Progress verbosity classification and filtering helpers."""

from __future__ import annotations

from typing import Any, Literal

ProgressVerbosity = Literal["minimal", "normal", "detailed", "debug"]
ProgressCategory = Literal[
    "assistant_text",
    "protocol",
    "subagent_progress",
    "subagent_custom",
    "tool_activity",
    "thinking",
    "error",
    "debug",
]


_SUBAGENT_PREFIXES = frozenset(
    {
        "soothe.research.",
        "soothe.browser.",
        "soothe.claude.",
        "soothe.skillify.",
        "soothe.weaver.",
    }
)

_PROTOCOL_PREFIXES = frozenset(
    {
        "soothe.iteration.",
        "soothe.goal.",
    }
)


# Key subagent events that should be visible at normal verbosity
_SUBAGENT_PROGRESS_EVENTS = frozenset(
    {
        "soothe.browser.step",
        "soothe.browser.cdp",
        "soothe.research.web_search",
        "soothe.research.search_done",
        "soothe.research.queries_generated",
        "soothe.research.complete",
    }
)


def classify_custom_event(namespace: tuple[Any, ...], data: dict[str, Any]) -> ProgressCategory:
    """Classify a custom event into a verbosity category."""
    etype = str(data.get("type", ""))
    if etype == "soothe.error":
        return "error"
    if etype.startswith("soothe."):
        if "thinking" in etype or "heartbeat" in etype:
            return "thinking"
        # Key user-facing events visible at normal verbosity
        if etype in _SUBAGENT_PROGRESS_EVENTS:
            return "subagent_progress"
        if any(etype.startswith(prefix) for prefix in _SUBAGENT_PREFIXES):
            return "subagent_custom"
        return "protocol"
    if namespace:
        if "thinking" in etype or "heartbeat" in etype:
            return "thinking"
        return "subagent_custom"
    if "thinking" in etype or "heartbeat" in etype:
        return "thinking"
    return "debug"


def should_show(category: ProgressCategory, verbosity: ProgressVerbosity) -> bool:
    """Return whether a progress category is visible at the given verbosity."""
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
