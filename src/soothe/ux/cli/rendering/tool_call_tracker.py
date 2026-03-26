"""Track tool call start/complete pairs for tree rendering.

This module implements the two-level tree structure for tool calls,
matching tool start events with their completion events to render as
parent/child tree nodes. See IG-053 for design details.

Example:
    ⚙ WebSearch("Iran wars")
      └ ✓ 10 results in 7.6s
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ToolCallState:
    """State for a pending tool call.

    Attributes:
        tool_name: Display name of the tool (CamelCase).
        tool_call_id: Unique identifier for the tool call.
        start_time: Unix timestamp when the call started.
        line_index: Terminal line where parent event was rendered.
        args_summary: Summary of arguments (e.g., "query='test'").
    """

    tool_name: str
    tool_call_id: str
    start_time: float
    line_index: int
    args_summary: str


@dataclass
class ToolCallTracker:
    """Track tool call start/complete pairs for tree rendering.

    The tracker maintains a mapping of pending tool calls (started but not
    yet completed) to enable rendering them as two-level trees:

    Example:
        ⚙ ToolName(args)
          └ ✓ result summary

    Attributes:
        pending: Map of tool_call_id to ToolCallState.
        line_counter: Counter for tracking terminal line positions.
    """

    pending: dict[str, ToolCallState] = field(default_factory=dict)
    line_counter: int = 0

    def register_start(
        self,
        tool_name: str,
        tool_call_id: str,
        args_summary: str,
    ) -> int:
        """Register a tool call start event.

        Args:
            tool_name: Display name of the tool.
            tool_call_id: Unique identifier for this tool call.
            args_summary: Summary of arguments.

        Returns:
            Line index where the parent event should be rendered.
        """
        state = ToolCallState(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            start_time=time.time(),
            line_index=self.line_counter,
            args_summary=args_summary,
        )
        self.pending[tool_call_id] = state
        self.line_counter += 1
        return state.line_index

    def register_complete(self, tool_call_id: str) -> ToolCallState | None:
        """Register a tool call completion event.

        Args:
            tool_call_id: Unique identifier for the tool call.

        Returns:
            ToolCallState if found, None if not tracked.
        """
        state = self.pending.pop(tool_call_id, None)
        if state:
            self.line_counter += 1
        return state

    def get_pending(self) -> list[ToolCallState]:
        """Get list of pending tool calls (for cleanup/debug).

        Returns:
            List of ToolCallState for pending calls.
        """
        return list(self.pending.values())

    def clear(self) -> None:
        """Clear all pending tool calls."""
        self.pending.clear()
        self.line_counter = 0
