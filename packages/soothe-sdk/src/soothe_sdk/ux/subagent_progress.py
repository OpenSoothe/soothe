"""Helper functions for subagent event processing.

This module provides utilities for CLI/TUI to extract subagent information
from curated ``soothe.subagent.*`` wire types (IG-339).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soothe_sdk.client.protocol import preview_first
from soothe_sdk.core.subagent_wire import (
    SUBAGENT_BROWSER_COMPLETED,
    SUBAGENT_BROWSER_STARTED,
    SUBAGENT_BROWSER_STEP_COMPLETED,
    SUBAGENT_CLAUDE_COMPLETED,
    SUBAGENT_CLAUDE_FAILED,
    SUBAGENT_CLAUDE_STARTED,
    SUBAGENT_CLAUDE_STEP_COMPLETED,
    SUBAGENT_EXPLORE_COMPLETED,
    SUBAGENT_EXPLORE_MILESTONE,
    SUBAGENT_EXPLORE_STARTED,
    SUBAGENT_EXPLORE_STEP_COMPLETED,
    SUBAGENT_RESEARCH_COMPLETED,
    SUBAGENT_RESEARCH_GATHER_SUMMARY,
    SUBAGENT_RESEARCH_STARTED,
)


def get_subagent_name_from_event(event_type: str) -> str | None:
    """Extract built-in subagent id from a curated wire event type.

    Args:
        event_type: Full event type string.

    Returns:
        Subagent segment (e.g., ``explore``, ``research``) for ``soothe.subagent.<id>.…``,
        else None.

    Example:
        >>> get_subagent_name_from_event("soothe.subagent.explore.started")
        'explore'
        >>> get_subagent_name_from_event("soothe.cognition.plan.created")
        None
    """
    if not event_type.startswith("soothe.subagent."):
        return None

    parts = event_type.split(".")
    if len(parts) >= 4:
        return parts[2]  # soothe.subagent.<subagent>.<...>
    return None


def summarize_subagent_wire_activity(event_type: str, data: Mapping[str, Any]) -> str:
    """One short line for Task tool cards / compact CLI mirroring (metadata-only).

    Args:
        event_type: Allowlisted ``soothe.subagent.*`` type.
        data: Event payload (excluding ``type``).

    Returns:
        Non-empty summary string, or empty when nothing to show.
    """
    if event_type == SUBAGENT_BROWSER_STARTED:
        return preview_first(str(data.get("task_preview", "")), 120)
    if event_type == SUBAGENT_BROWSER_STEP_COMPLETED:
        parts = [
            str(data.get("status", "") or "").strip(),
            preview_first(str(data.get("action_preview", "")), 80),
            preview_first(str(data.get("url", "")), 80),
        ]
        return " · ".join(p for p in parts if p)
    if event_type == SUBAGENT_BROWSER_COMPLETED:
        ok = data.get("success", True)
        ms = int(data.get("duration_ms", 0) or 0)
        status = "done" if ok else "failed"
        return f"{status} ({ms}ms)" if ms else status

    if event_type == SUBAGENT_CLAUDE_STARTED:
        return preview_first(str(data.get("task_preview", "")), 120)
    if event_type == SUBAGENT_CLAUDE_STEP_COMPLETED:
        tn = str(data.get("tool_name", "") or "").strip()
        ip = preview_first(str(data.get("input_preview", "")), 80)
        if tn and ip:
            return f"{tn}({ip})"
        return tn or ip or "step"
    if event_type == SUBAGENT_CLAUDE_COMPLETED:
        cost = data.get("cost_usd", 0.0)
        ms = int(data.get("duration_ms", 0) or 0)
        try:
            c = float(cost)
        except (TypeError, ValueError):
            c = 0.0
        return f"${c:.2f}, {ms}ms"
    if event_type == SUBAGENT_CLAUDE_FAILED:
        return preview_first(str(data.get("message", "")), 120)

    if event_type == SUBAGENT_EXPLORE_STARTED:
        return str(data.get("search_target", "") or "").strip()
    if event_type == SUBAGENT_EXPLORE_MILESTONE:
        decision = str(data.get("decision", "") or "").strip()
        fc = int(data.get("findings_count", 0) or 0)
        it = int(data.get("iterations_used", 0) or 0)
        base = decision or "milestone"
        return f"{base} ({fc} findings, {it} iter)"
    if event_type == SUBAGENT_EXPLORE_STEP_COMPLETED:
        tn = str(data.get("tool_name", "") or "").strip()
        ap = preview_first(str(data.get("args_preview", "")), 60)
        if tn and ap:
            return f"{tn}({ap})"
        return tn or "tool"
    if event_type == SUBAGENT_EXPLORE_COMPLETED:
        tf = int(data.get("total_findings", 0) or 0)
        ms = int(data.get("duration_ms", 0) or 0)
        return f"{tf} findings ({ms}ms)"

    if event_type == SUBAGENT_RESEARCH_STARTED:
        return preview_first(str(data.get("topic_preview", "")), 120)
    if event_type == SUBAGENT_RESEARCH_GATHER_SUMMARY:
        rc = int(data.get("result_count", 0) or 0)
        st = int(data.get("sources_touched", 0) or 0)
        qp = preview_first(str(data.get("query_preview", "")), 60)
        tail = f"{rc} hits, {st} sources"
        return f"{qp} → {tail}" if qp else tail
    if event_type == SUBAGENT_RESEARCH_COMPLETED:
        al = int(data.get("answer_length", 0) or 0)
        ms = int(data.get("duration_ms", 0) or 0)
        return f"{al} chars ({ms}ms)"

    return ""


__all__ = [
    "get_subagent_name_from_event",
    "summarize_subagent_wire_activity",
]
