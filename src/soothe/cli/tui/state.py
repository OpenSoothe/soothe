"""TUI state management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.text import Text

from soothe.cli.message_processing import SharedState
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

    # Compose shared state for common fields
    shared: SharedState = field(default_factory=SharedState)

    # TUI-specific state
    tool_call_buffers: dict[str | int, dict[str, Any]] = field(default_factory=dict)
    activity_lines: list[Text] = field(default_factory=list)
    current_plan: Plan | None = None
    subagent_tracker: SubagentTracker = field(default_factory=SubagentTracker)
    errors: list[str] = field(default_factory=list)
    thread_id: str = ""
    last_user_input: str = ""
    plan_visible: bool = True  # Track plan tree visibility

    # Convenience properties to access shared state
    @property
    def full_response(self) -> list[str]:
        """Get full_response from shared state."""
        return self.shared.full_response

    @full_response.setter
    def full_response(self, value: list[str]) -> None:
        """Set full_response in shared state."""
        self.shared.full_response = value

    @property
    def seen_message_ids(self) -> set[str]:
        """Get seen_message_ids from shared state."""
        return self.shared.seen_message_ids

    @seen_message_ids.setter
    def seen_message_ids(self, value: set[str]) -> None:
        """Set seen_message_ids in shared state."""
        self.shared.seen_message_ids = value

    @property
    def name_map(self) -> dict[str, str]:
        """Get name_map from shared state."""
        return self.shared.name_map

    @name_map.setter
    def name_map(self, value: dict[str, str]) -> None:
        """Set name_map in shared state."""
        self.shared.name_map = value

    @property
    def multi_step_active(self) -> bool:
        """Get multi_step_active from shared state."""
        return self.shared.multi_step_active

    @multi_step_active.setter
    def multi_step_active(self, value: bool) -> None:
        """Set multi_step_active in shared state."""
        self.shared.multi_step_active = value

    @property
    def has_error(self) -> bool:
        """Get has_error from shared state."""
        return self.shared.has_error

    @has_error.setter
    def has_error(self, value: bool) -> None:
        """Set has_error in shared state."""
        self.shared.has_error = value
