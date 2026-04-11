"""TUI state management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.text import Text

from soothe.protocols.planner import Plan
from soothe.utils.text_preview import preview_first


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
                activity = preview_first(st.last_activity, 50) or "running..."
                lines.append(Text.assemble(("  ", ""), (f"[{tag}] ", "magenta"), (activity, "yellow")))
        return lines


@dataclass
class TuiState:
    """Mutable display state shared by TUI frontends."""

    # Shared state fields (formerly in SharedState)
    full_response: list[str] = field(default_factory=list)
    seen_message_ids: set[str] = field(default_factory=set)
    name_map: dict[str, str] = field(default_factory=dict)
    multi_step_active: bool = False
    has_error: bool = False
    # Track pending tool calls for streaming arg accumulation (IG-053)
    # Maps tool_call_id -> {'name': str, 'args_str': str, 'emitted': bool, 'is_main': bool}
    pending_tool_calls: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Track internal context for research tool filtering (IG-064)
    internal_context_active: bool = False

    # TUI-specific state
    tool_call_buffers: dict[str | int, dict[str, Any]] = field(default_factory=dict)
    activity_lines: list[Text] = field(default_factory=list)
    current_plan: Plan | None = None
    subagent_tracker: SubagentTracker = field(default_factory=SubagentTracker)
    errors: list[str] = field(default_factory=list)
    thread_id: str = ""
    last_user_input: str = ""
    plan_visible: bool = True  # Track plan tree visibility

    # Streaming state for Claude Code-style continuous updates
    streaming_text_buffer: str = ""  # Accumulates streaming assistant text for live updates
    streaming_active: bool = False  # Whether we're currently streaming assistant text
    last_assistant_output: str = ""  # Stores final assistant output for copy-last action
    current_tool_calls: dict[str, dict[str, str]] = field(default_factory=dict)  # Tracks in-progress tool calls by ID
    # Each entry: {"name": str, "args_summary": str}
