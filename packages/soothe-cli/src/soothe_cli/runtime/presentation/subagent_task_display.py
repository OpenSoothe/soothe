"""Format subagent Task-scope assistant blobs for CLI/TUI.

Deep Research emits structured JSON in subgraph assistant streams. Clients show
user-facing summaries only; internal planning JSON is suppressed.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any


def _is_deep_research_internal_json_object(obj: dict[str, Any]) -> bool:
    """True when ``obj`` is Deep Research engine scratch (not a user-facing report)."""
    keys = set(obj.keys())
    if "sub_questions" in keys:
        return True
    if "queries" in keys and "query" not in keys:
        return True
    if "is_sufficient" in keys or "follow_up_queries" in keys or "knowledge_gap" in keys:
        return True
    return False


def _iter_embedded_json_objects(raw: str) -> Iterator[dict[str, Any]]:
    """Yield dict objects embedded anywhere in ``raw`` (prose + concatenated JSON)."""
    dec = json.JSONDecoder()
    i = 0
    s = raw
    n = len(s)
    while i < n:
        brace = s.find("{", i)
        if brace < 0:
            break
        try:
            obj, end = dec.raw_decode(s, brace)
        except json.JSONDecodeError:
            i = brace + 1
            continue
        if isinstance(obj, dict):
            yield obj
        i = end


def _strip_concatenated_json_objects(raw: str, *, predicate) -> str:
    """Remove JSON objects matching ``predicate``; keep surrounding prose."""
    stripped = raw.strip()
    if not stripped:
        return raw

    dec_objects: list[tuple[int, int, dict[str, Any]]] = []
    dec = json.JSONDecoder()
    i = 0
    n = len(stripped)
    while i < n:
        while i < n and stripped[i].isspace():
            i += 1
        if i >= n:
            break
        try:
            obj, end = dec.raw_decode(stripped, i)
        except json.JSONDecodeError:
            break
        if isinstance(obj, dict) and predicate(obj):
            dec_objects.append((i, end, obj))
        i = end

    if not dec_objects:
        return raw

    parts: list[str] = []
    cursor = 0
    for start, end, _obj in dec_objects:
        if start > cursor:
            parts.append(stripped[cursor:start])
        cursor = end
    if cursor < n:
        parts.append(stripped[cursor:])
    return " ".join("".join(parts).split())


def format_subagent_task_assistant_for_display(
    raw: str,
    *,
    subagent_type: str | None = None,
) -> str:
    """Return display-safe assistant text for a delegated task namespace.

    Args:
        raw: Full assistant text from a subgraph namespace.
        subagent_type: Built-in subagent id when known (``deep_research``, …).

    Returns:
        Scrubbed one-line text, or ``""`` when only internal payloads remain.
    """
    agent = (subagent_type or "").strip().lower()
    text = raw
    if agent in ("deep_research", "academic_research"):
        stripped = text.strip()
        internal_present = any(
            _is_deep_research_internal_json_object(obj)
            for obj in _iter_embedded_json_objects(stripped)
        )
        if internal_present:
            return ""
        text = _strip_concatenated_json_objects(
            text, predicate=_is_deep_research_internal_json_object
        )
    return (text or "").strip()


__all__ = [
    "format_subagent_task_assistant_for_display",
]
