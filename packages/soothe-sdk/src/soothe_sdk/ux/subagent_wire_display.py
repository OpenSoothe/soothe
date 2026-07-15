"""Unified display protocol for curated ``soothe.subagent.*`` wire events.

Maps sparse subagent progress signals to TUI/CLI render kinds: activity notes,
synthetic tool rows, or lifecycle finalization.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from soothe_sdk.wire.protocol import preview_first


class SubagentWireRenderKind(StrEnum):
    """How clients should render a subagent wire event."""

    ACTIVITY_NOTE = "activity_note"
    ACTIVITY_ROW = "activity_row"
    LIFECYCLE_END = "lifecycle_end"


_ACTIVITY_NOTE_SUFFIXES = (
    ".started",
    ".progress",
    ".milestone",
    ".requested",
    ".answered",
    ".deferred",
)

_ACTIVITY_ROW_SUFFIXES = (
    ".step.completed",
    ".gather.summary",
    ".crawl.summary",
)


def classify_subagent_wire_render(event_type: str) -> SubagentWireRenderKind | None:
    """Classify a curated subagent wire event for client rendering.

    Args:
        event_type: Full wire type (``soothe.subagent.<id>.<signal>``).

    Returns:
        Render kind, or ``None`` when the type is not a known subagent signal.
    """
    et = str(event_type or "").strip()
    if not et.startswith("soothe.subagent."):
        return None
    if et.endswith(_ACTIVITY_ROW_SUFFIXES):
        return SubagentWireRenderKind.ACTIVITY_ROW
    if et.endswith(".completed") or et.endswith(".failed"):
        return SubagentWireRenderKind.LIFECYCLE_END
    if et.endswith(_ACTIVITY_NOTE_SUFFIXES):
        return SubagentWireRenderKind.ACTIVITY_NOTE
    return None


def subagent_wire_row_params(
    event_type: str,
    data: Mapping[str, Any],
) -> tuple[str, dict[str, Any], str, int] | None:
    """Map row-style subagent wire events to synthetic tool-row fields.

    Returns:
        ``(tool_name, args, phase, duration_ms)`` or ``None`` when not a row signal.
    """
    et = str(event_type or "").strip()
    if et.endswith(".gather.summary"):
        query = str(data.get("query_preview", "") or "").strip()
        rc = int(data.get("result_count", 0) or 0)
        st = int(data.get("sources_touched", 0) or 0)
        preview = query
        if rc or st:
            tail = f"{rc} hits, {st} sources"
            preview = f"{query} → {tail}" if query else tail
        tool_name = "AcademicSearch" if ".academic_research." in et else "WebSearch"
        return tool_name, {"query": preview or query}, "success", 0
    if et.endswith(".crawl.summary"):
        urls = int(data.get("urls_crawled", 0) or 0)
        success = int(data.get("success_count", 0) or 0)
        preview = f"{success}/{urls} URLs"
        return "Crawl", {"urls": preview}, "success", 0
    if et.endswith(".step.completed"):
        tool_name = str(data.get("tool_name", "") or "").strip()
        args_preview = str(data.get("args_preview", "") or "").strip()
        if not tool_name and data.get("step_index") is not None:
            try:
                idx = int(data.get("step_index"))
            except (TypeError, ValueError):
                idx = 0
            tool_name = f"BrowserStep#{idx}" if idx > 0 else "BrowserStep"
        if not tool_name:
            tool_name = "Step"
        if not args_preview:
            action = preview_first(str(data.get("action_preview", "")), 80)
            url = preview_first(str(data.get("url", "")), 80)
            title = preview_first(str(data.get("title", "")), 40)
            if action:
                args_preview = action
            elif url:
                args_preview = url
            if title and args_preview and title not in args_preview:
                args_preview = f"{args_preview} ({title})"
            elif title and not args_preview:
                args_preview = title
        status = str(data.get("status", "done") or "done").strip().lower()
        phase = "error" if status in ("error", "failed") else "success"
        duration_ms = int(data.get("duration_ms", 0) or 0)
        args = {"preview": args_preview} if args_preview else {}
        return tool_name, args, phase, duration_ms
    return None


__all__ = [
    "SubagentWireRenderKind",
    "classify_subagent_wire_render",
    "subagent_wire_row_params",
]
