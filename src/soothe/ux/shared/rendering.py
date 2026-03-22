"""Shared TUI utilities for state management and rendering.

This module contains reusable display helpers used by both TUI and headless modes.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from rich.text import Text
from rich.tree import Tree

from soothe.protocols.planner import Plan

if TYPE_CHECKING:
    from soothe.ux.tui.state import TuiState

logger = logging.getLogger(__name__)

_TASK_NAME_RE = re.compile(r'"?name"?\s*:\s*"?(\w+)"?')
_STATUS_MARKERS: dict[str, tuple[str, str]] = {
    "pending": ("[ ]", "dim"),
    "in_progress": ("[>]", "bold yellow"),
    "completed": ("[+]", "bold green"),
    "failed": ("[x]", "bold red"),
}


def extract_text_from_ai_message(msg: Any) -> list[str]:
    """Extract text content from AI messages for conversation logging.

    Handles both LangChain AIMessage objects and deserialized dicts.

    Args:
        msg: Message object (AIMessage or dict).

    Returns:
        List of text strings extracted from the message.
    """
    texts: list[str] = []
    try:
        # Handle LangChain AIMessage objects
        if hasattr(msg, "content_blocks") and msg.content_blocks:
            for block in msg.content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        texts.append(text)
        elif hasattr(msg, "content") and isinstance(msg.content, str) and msg.content:
            texts.append(msg.content)
        # Handle deserialized dict
        elif isinstance(msg, dict):
            blocks = msg.get("content_blocks") or []
            if not blocks:
                content = msg.get("content", "")
                if isinstance(content, str) and content:
                    texts.append(content)
            else:
                for block in blocks:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            texts.append(text)
    except Exception:
        logger.debug("Failed to extract assistant text", exc_info=True)

    return texts


def render_plan_tree(plan: Plan, title: str | None = None) -> Tree:
    """Render a plan as a Rich Tree with status markers, dependencies, and activities."""
    label = title or f"Plan: {plan.goal}"
    tree = Tree(Text(label, style="bold cyan"))

    # Add general activity under root if present
    if plan.general_activity:
        activity_node = tree.add(Text("General", style="dim italic"))
        activity_node.add(Text(plan.general_activity, style="dim"))

    # Add steps
    for step in plan.steps:
        marker, style = _STATUS_MARKERS.get(step.status, ("[ ]", "dim"))
        step_style = {"in_progress": "yellow", "completed": "green"}.get(step.status, "dim")
        parts: list[Text | str] = [Text(marker, style=style), " ", Text(step.description, style=step_style)]
        if step.depends_on:
            dep_str = ", ".join(step.depends_on)
            parts.append(Text(f"  (< {dep_str})", style="dim italic"))

        # Add step as tree node
        step_node = tree.add(Text.assemble(*parts))

        # If step is in_progress and has activity, add it as a child node
        if step.status == "in_progress" and step.current_activity:
            # Indent and style the activity
            activity_text = Text(step.current_activity, style="dim")
            step_node.add(activity_text)

    return tree


def _display_subagent_name(name: str) -> str:
    """Return friendly display name for a subagent id."""
    from soothe.ux.cli.commands.subagent_names import SUBAGENT_DISPLAY_NAMES

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
