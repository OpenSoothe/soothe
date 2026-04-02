"""Shared TUI utilities for state management and rendering.

This module contains reusable display helpers used by both TUI and headless modes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from soothe.foundation.ai_message import extract_text_from_ai_message
from soothe.plan.rich_tree import _TASK_NAME_RE, render_plan_tree

if TYPE_CHECKING:
    from soothe.ux.tui.state import TuiState

# Re-export for callers that imported from rendering
__all__ = [
    "extract_text_from_ai_message",
    "render_plan_tree",
    "resolve_namespace_label",
    "update_name_map_from_tool_calls",
]


def _display_subagent_name(name: str) -> str:
    """Return friendly display name for a subagent id."""
    from soothe.ux.shared.subagent_routing import SUBAGENT_DISPLAY_NAMES

    return SUBAGENT_DISPLAY_NAMES.get(name.lower(), name.replace("_", " ").title())


def update_name_map_from_tool_calls(message_obj: object, name_map: dict[str, str]) -> None:
    """Update tool-call-id -> display name mapping from AIMessage/tool calls.

    This is the shared implementation used by both TUI and headless modes.
    """
    tool_calls = getattr(message_obj, "tool_calls", None) or []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        if tc.get("name") != "task":
            continue
        call_id = str(tc.get("id", ""))
        args = tc.get("args", {})
        raw_name = ""
        if isinstance(args, dict):
            raw_name = str(args.get("agent", "") or args.get("name", ""))
        elif args:
            match = _TASK_NAME_RE.search(str(args))
            if match:
                raw_name = match.group(1)
        if call_id and raw_name:
            name_map[call_id] = _display_subagent_name(raw_name)


def _update_name_map_from_ai_message(state: TuiState, message_obj: object) -> None:
    """Update name mapping from AIMessage (TuiState wrapper)."""
    update_name_map_from_tool_calls(message_obj, state.name_map)


def resolve_namespace_label(namespace: tuple[str, ...], name_map: dict[str, str]) -> str:
    """Resolve namespace tuple to friendly display label.

    This is the shared implementation used by both TUI and headless modes.
    """
    if not namespace:
        return "main"
    parts: list[str] = []
    for segment in namespace:
        seg_str = str(segment)
        if seg_str in name_map:
            parts.append(name_map[seg_str])
        elif seg_str.startswith("tools:"):
            tool_id = seg_str.split(":", 1)[1] if ":" in seg_str else seg_str
            parts.append(name_map.get(tool_id, seg_str))
        else:
            parts.append(seg_str)
    return "/".join(parts)


def _resolve_namespace_label(namespace: tuple[str, ...], state: TuiState) -> str:
    """Resolve namespace tuple to friendly display label (TuiState wrapper)."""
    return resolve_namespace_label(namespace, state.name_map)
