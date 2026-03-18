"""TUI state management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.text import Text

from soothe.protocols.planner import Plan


@dataclass
class _SubagentState:
    subagent_id: str
    status: str = "running"
    last_activity: str = ""


class SubagentTracker:
    """Tracks per-subagent progress for display."""

    def __init__(self) -> None:
        """Initialize the subagent tracker."""
        self._states: dict[str, _SubagentState] = {}

    def update_from_custom(self, label: str, data: dict[str, Any]) -> None:
        """Update tracker from a subagent custom event."""
        sid = label or "unknown"
        if sid not in self._states:
            self._states[sid] = _SubagentState(subagent_id=sid)
        event_type = data.get("type", "")
        summary = str(data.get("topic", data.get("query", event_type)))[:60]
        self._states[sid].last_activity = summary

    def mark_done(self, sid: str) -> None:
        """Mark a subagent as done."""
        if sid in self._states:
            self._states[sid].status = "done"

    def render(self) -> list[Text]:
        """Return displayable status lines for active subagents."""
        lines: list[Text] = []
        for st in list(self._states.values())[-3:]:
            tag = st.subagent_id.split(":")[-1] if ":" in st.subagent_id else st.subagent_id
            if st.status == "done":
                lines.append(Text.assemble(("  ", ""), (f"[{tag}] ", "green"), ("done", "green")))
            else:
                activity = st.last_activity[:50] or "running..."
                lines.append(Text.assemble(("  ", ""), (f"[{tag}] ", "magenta"), (activity, "yellow")))
        return lines


@dataclass
class TuiState:
    """Mutable display state shared by TUI frontends."""

    full_response: list[str] = field(default_factory=list)
    tool_call_buffers: dict[str | int, dict[str, Any]] = field(default_factory=dict)
    name_map: dict[str, str] = field(default_factory=dict)
    activity_lines: list[Text] = field(default_factory=list)
    current_plan: Plan | None = None
    subagent_tracker: SubagentTracker = field(default_factory=SubagentTracker)
    seen_message_ids: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    thread_id: str = ""
    last_user_input: str = ""
