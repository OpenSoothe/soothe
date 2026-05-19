"""Compact Task delegation labels for display helpers."""

from __future__ import annotations


def brief_task_tool_call_id(tool_call_id: str) -> str:
    """Shorten LangChain-style ids (e.g. ``functions.task:0``) for display prefixes."""
    tid = (tool_call_id or "").strip()
    if not tid:
        return ""
    if ":" in tid:
        tail = tid.rsplit(":", 1)[-1]
        if tail.isdigit():
            return f"#{tail}"
    if len(tid) > 20:
        return tid[-8:]
    return tid


def format_task_scope_prefix(tool_call_id: str, subagent_type: str) -> str:
    """Prefix for Task subgraph lines: ``Task(explore):#0``."""
    short = brief_task_tool_call_id(tool_call_id)
    st = (subagent_type or "?").strip() or "?"
    return f"Task({st}):{short}"


__all__ = [
    "brief_task_tool_call_id",
    "format_task_scope_prefix",
]
