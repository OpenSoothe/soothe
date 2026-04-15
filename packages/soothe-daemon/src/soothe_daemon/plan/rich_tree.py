"""Render planner ``Plan`` models as Rich trees."""

from __future__ import annotations

import re

from rich.text import Text
from rich.tree import Tree

from soothe_daemon.protocols.planner import Plan

_TASK_NAME_RE = re.compile(r'"?name"?\s*:\s*"?(\w+)"?')
_STATUS_MARKERS: dict[str, tuple[str, str]] = {
    "pending": ("[ ]", "dim"),
    "in_progress": ("[>]", "bold yellow"),
    "completed": ("[+]", "bold green"),
    "failed": ("[x]", "bold red"),
}


def render_plan_tree(plan: Plan, title: str | None = None) -> Tree:
    """Render a plan as a Rich Tree with status markers, dependencies, and activities."""
    label = title or f"Plan: {plan.goal}"
    tree = Tree(Text(label, style="bold cyan"))

    if plan.reasoning:
        reasoning_node = tree.add(Text("Reasoning", style="dim italic"))
        reasoning_node.add(Text(plan.reasoning, style="dim"))

    if plan.general_activity:
        activity_node = tree.add(Text("General", style="dim italic"))
        activity_node.add(Text(plan.general_activity, style="dim"))

    for step in plan.steps:
        marker, style = _STATUS_MARKERS.get(step.status, ("[ ]", "dim"))
        step_style = {"in_progress": "yellow", "completed": "green"}.get(step.status, "dim")
        parts: list[Text | str] = [
            Text(marker, style=style),
            " ",
            Text(step.description, style=step_style),
        ]
        if step.depends_on:
            dep_str = ", ".join(step.depends_on)
            parts.append(Text(f"  (< {dep_str})", style="dim italic"))

        step_node = tree.add(Text.assemble(*parts))

        if step.status == "in_progress" and step.current_activity:
            activity_text = Text(step.current_activity, style="dim")
            step_node.add(activity_text)

    return tree


__all__ = ["_STATUS_MARKERS", "_TASK_NAME_RE", "render_plan_tree"]
