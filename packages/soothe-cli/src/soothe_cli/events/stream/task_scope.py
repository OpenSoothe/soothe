"""Compact Task delegation labels for CLI (IG-334)."""

from __future__ import annotations


def brief_task_tool_call_id(tool_call_id: str) -> str:
    """Shorten LangChain-style ids (e.g. ``functions.task:0``) for stderr prefixes.

    Args:
        tool_call_id: Raw provider tool call id.

    Returns:
        Numeric suffix as ``#N`` when parseable; otherwise a truncated opaque id.
    """
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
    """Prefix for Task subgraph lines: ``Task(explore):#0`` (no brackets)."""
    short = brief_task_tool_call_id(tool_call_id)
    st = (subagent_type or "?").strip() or "?"
    return f"Task({st}):{short}"


def format_task_subagent_line(subagent_type: str, task_description: str) -> str:
    """Single-line delegated UX: ``Task(explore, \"…\")`` with safe quoting."""
    st = (subagent_type or "?").strip() or "?"
    desc = task_description or ""
    escaped = desc.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip()
    return f'Task({st}, "{escaped}")'


__all__ = [
    "brief_task_tool_call_id",
    "format_task_scope_prefix",
    "format_task_subagent_line",
]
