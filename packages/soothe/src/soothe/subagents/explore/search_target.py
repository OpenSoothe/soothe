"""Resolve explore search target from graph state and task messages (IG-326)."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage


def _stringify_human_content(content: Any) -> str:
    """Normalize HumanMessage content to plain text."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts).strip()
    if content is None:
        return ""
    return str(content).strip()


def resolve_explore_search_target(
    messages: list[Any] | None,
    explicit: str | None = None,
) -> str:
    """Return the effective filesystem search goal string.

    Prefers a non-empty ``explicit`` value from graph state (``search_target``).
    Otherwise uses the text of the most recent ``HumanMessage`` in ``messages``
    (how the ``task`` tool passes the subagent brief).

    Args:
        messages: Conversation messages (newest relevant content may be last).
        explicit: Optional ``state['search_target']`` value.

    Returns:
        Stripped target string, or empty string if nothing usable was found.
    """
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    if not messages:
        return ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            text = _stringify_human_content(msg.content)
            if text:
                return text
    return ""
