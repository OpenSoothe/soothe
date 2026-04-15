"""Shared TUI utilities for state management and rendering.

This module contains reusable display helpers used by both TUI and headless modes.
"""

from __future__ import annotations

from soothe_sdk import _TASK_NAME_RE

__all__ = [
    "update_name_map_from_tool_calls",
]


def _display_subagent_name(name: str) -> str:
    """Return friendly display name for a subagent id."""
    from soothe_cli.shared.subagent_routing import SUBAGENT_DISPLAY_NAMES

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
