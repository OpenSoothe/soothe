"""Format explore subagent Task-scope JSON assistant blobs for CLI/TUI (IG-311).

Explore emits structured JSON in ``AIMessage`` content (assessment tokens and final
``ExploreResult``). Clients show ``summary`` text only; assessment ``decision`` blobs
are suppressed (empty string).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any


def iter_concatenated_json_objects(raw: str) -> Iterator[dict[str, Any]]:
    """Yield dict objects from a string that may contain multiple JSON objects concatenated."""
    dec = json.JSONDecoder()
    i = 0
    s = raw
    n = len(s)
    while i < n:
        while i < n and s[i].isspace():
            i += 1
        if i >= n:
            break
        try:
            obj, end = dec.raw_decode(s, i)
        except json.JSONDecodeError:
            break
        i = end
        if isinstance(obj, dict):
            yield obj


def format_explore_task_json_blob_for_display(raw: str) -> str:
    """If ``raw`` looks like explore JSON, return display text; else return ``raw``.

    Prefers ``summary`` from an object that includes ExploreResult-like keys (``matches``,
    ``target``), then any non-empty ``summary``. Concatenated assessment objects that only
    contain ``decision`` yield an empty string (suppress — wire milestones cover progress).

    Args:
        raw: Full assistant text (possibly repaired concatenation).

    Returns:
        One-line summary, ``""`` when only decisions, or ``raw`` when not explore JSON.
    """
    stripped = raw.strip()
    if not stripped.startswith("{"):
        return raw

    objs = list(iter_concatenated_json_objects(stripped))
    if not objs:
        return raw

    for obj in reversed(objs):
        if not isinstance(obj, dict):
            continue
        summary = obj.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            continue
        if "matches" in obj or "target" in obj:
            return " ".join(summary.split())

    for obj in reversed(objs):
        if not isinstance(obj, dict):
            continue
        summary = obj.get("summary")
        if isinstance(summary, str) and summary.strip():
            return " ".join(summary.split())

    decisions: list[str] = []
    for obj in objs:
        if not isinstance(obj, dict):
            continue
        d = obj.get("decision")
        if isinstance(d, str) and d.strip():
            decisions.append(d.strip())

    if decisions:
        return ""

    return raw


__all__ = [
    "format_explore_task_json_blob_for_display",
    "iter_concatenated_json_objects",
]
