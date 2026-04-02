"""TUI renderer implementing RendererProtocol for Rich panel output.

This module provides the TuiRenderer class that outputs events to
Rich panel widgets with streaming support and visual styling.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from rich.console import RenderableType
from rich.text import Text

from soothe.tools.display_names import get_tool_display_name
from soothe.ux.shared.event_formatter import build_event_summary
from soothe.ux.shared.message_processing import format_tool_call_args
from soothe.ux.tui.utils import (
    DOT_COLORS,
    format_duration_enhanced,
    get_icon,
    make_dot_line,
    make_tool_block,
)

if TYPE_CHECKING:
    from soothe.protocols.planner import Plan

logger = logging.getLogger(__name__)

# Type aliases for callbacks
PanelWriteCallback = Callable[[RenderableType], None] | None
PanelUpdateCallback = Callable[[RenderableType], None] | None
StatusUpdateCallback = Callable[[str], None] | None
PlanRefreshCallback = Callable[[], None] | None


@dataclass
class TuiRendererState:
    """TUI-specific display state."""

    # Streaming text buffer for live updates
    streaming_text_buffer: str = ""

    # Whether actively streaming assistant text
    streaming_active: bool = False

    # Last complete assistant output for copy-to-clipboard
    last_assistant_output: str = ""

    # Track in-progress tool calls for result correlation
    current_tool_calls: dict[str, dict[str, str]] = field(default_factory=dict)

    # Track tool call start times for duration display (RFC-0020)
    tool_call_start_times: dict[str, float] = field(default_factory=dict)

    # Track if final response was already emitted via custom event (deduplication)
    final_response_emitted: bool = False


class TuiRenderer:
    """TUI renderer for Rich panel widgets.

    Implements RendererProtocol callbacks for TUI mode:
    - Assistant text -> Conversation panel (streaming with live updates)
    - Tool calls/results -> Panel blocks with tree format
    - Progress events -> Panel with colored dots
    - Plan updates -> Refresh plan tree widget

    Usage:
        renderer = TuiRenderer(
            on_panel_write=panel.append_entry,
            on_panel_update_last=panel.update_last_entry,
            on_status_update=update_status_bar,
            on_plan_refresh=refresh_plan_tree,
        )
        processor = EventProcessor(renderer, verbosity="normal")
    """

    def __init__(
        self,
        *,
        on_panel_write: PanelWriteCallback = None,
        on_panel_update_last: PanelUpdateCallback = None,
        on_status_update: StatusUpdateCallback = None,
        on_plan_refresh: PlanRefreshCallback = None,
    ) -> None:
        """Initialize TUI renderer.

        Args:
            on_panel_write: Callback to append to conversation panel.
            on_panel_update_last: Callback to update last panel entry.
            on_status_update: Callback for status bar updates.
            on_plan_refresh: Callback to refresh plan tree widget.
        """
        self._on_panel_write = on_panel_write
        self._on_panel_update_last = on_panel_update_last
        self._on_status_update = on_status_update
        self._on_plan_refresh = on_plan_refresh
        self._state = TuiRendererState()

    @property
    def last_assistant_output(self) -> str:
        """Get last assistant output for copy-to-clipboard."""
        return self._state.last_assistant_output

    @property
    def streaming_active(self) -> bool:
        """Whether currently streaming assistant text."""
        return self._state.streaming_active

    def mark_final_response_emitted(self) -> None:
        """Mark that final response was emitted via custom event.

        Prevents duplicate output when the same content comes through
        the AIMessage stream.
        """
        self._state.final_response_emitted = True

    def on_assistant_text(
        self,
        text: str,
        *,
        is_main: bool,
        is_streaming: bool,  # noqa: ARG002
    ) -> None:
        """Stream assistant text to panel.

        Args:
            text: Text content to display.
            is_main: True if from main agent.
            is_streaming: True if partial chunk.
        """
        # Skip if final response was already emitted via custom event
        if self._state.final_response_emitted:
            return

        if is_main:
            self._stream_main_text(text)
        else:
            # Subagent text shown with prefix
            brief = text.replace("\n", " ")[:80]
            if self._on_panel_write:
                self._on_panel_write(make_dot_line(DOT_COLORS["subagent"], f"[subagent] {brief}"))

    def _stream_main_text(self, text: str) -> None:
        """Stream main agent text with live updates.

        Accumulates text in buffer and updates panel entry in-place.

        Args:
            text: Text chunk to append.
        """
        self._state.streaming_text_buffer += text
        display_text = make_dot_line(
            DOT_COLORS["assistant"],
            self._state.streaming_text_buffer,
        )

        if not self._state.streaming_active:
            # First chunk - append new entry
            self._state.streaming_active = True
            if self._on_panel_write:
                self._on_panel_write(display_text)
            else:
                logger.warning("TuiRenderer: on_panel_write is None, cannot write first chunk")
        elif self._on_panel_update_last:
            # Subsequent chunks - update the last entry in place
            self._on_panel_update_last(display_text)
        elif self._on_panel_write:
            # Fallback if update not available
            logger.warning("TuiRenderer: on_panel_update_last is None, falling back to write")
            self._on_panel_write(display_text)

    def on_tool_call(
        self,
        name: str,
        args: dict[str, Any],
        tool_call_id: str,
        *,
        is_main: bool,  # noqa: ARG002
    ) -> None:
        """Write tool call block with progress indicator.

        Args:
            name: Tool name.
            args: Parsed arguments.
            tool_call_id: Tool call identifier.
            is_main: True if from main agent.
        """
        if not self._on_panel_write:
            return

        display_name = get_tool_display_name(name)
        args_summary = format_tool_call_args(name, {"args": args})

        # Detect long-running tools for special indicator
        is_long_running = self._is_long_running_tool(name)

        # Store for result correlation
        if tool_call_id:
            self._state.current_tool_calls[tool_call_id] = {
                "name": display_name,
                "args_summary": args_summary,
            }
            # Track start time for duration display (RFC-0020)
            self._state.tool_call_start_times[tool_call_id] = time.time()

        # Finalize streaming before tool block
        if self._state.streaming_active:
            self._state.streaming_active = False
            self._state.streaming_text_buffer = ""

        # Use enhanced tool block with progress indicator
        self._on_panel_write(make_tool_block(display_name, args_summary, status="running"))

        # Optional: Add separate progress line for long-running tools
        if is_long_running:
            progress_line = Text()
            progress_line.append("  ⏳ ", style="dim yellow")
            progress_line.append("Running...", style="dim")
            self._on_panel_write(progress_line)

    def on_tool_result(
        self,
        name: str,  # noqa: ARG002
        result: str,
        tool_call_id: str,
        *,
        is_error: bool,
        is_main: bool,  # noqa: ARG002
    ) -> None:
        """Write tool result with enhanced duration formatting.

        Args:
            name: Tool name.
            result: Result content (truncated).
            tool_call_id: Tool call identifier.
            is_error: True if result indicates error.
            is_main: True if from main agent.
        """
        if not self._on_panel_write:
            return

        # Clear tracked tool call
        if tool_call_id:
            self._state.current_tool_calls.pop(tool_call_id, None)

        # Calculate duration
        duration_ms = 0
        if tool_call_id and tool_call_id in self._state.tool_call_start_times:
            start_time = self._state.tool_call_start_times.pop(tool_call_id)
            duration_ms = int((time.time() - start_time) * 1000)

        # Format duration with enhanced formatting
        duration_str, duration_style = format_duration_enhanced(duration_ms, context="tool")

        # Choose icon and color
        icon_category = "tool_error" if is_error else "tool_success"
        icon = get_icon(icon_category)
        color = DOT_COLORS[icon_category]

        # Create result line
        result_line = Text()
        result_line.append("  └ ", style="dim")
        result_line.append(icon + " ", style=color)
        result_line.append(result[:80], style="dim")  # RFC-0020 compliance: 80 char limit

        # Add duration with appropriate styling
        if duration_ms > 0:
            result_line.append(f" [{duration_str}]", style=duration_style)

        self._on_panel_write(result_line)

    def on_status_change(self, state: str) -> None:
        """Update status bar.

        Args:
            state: New daemon state.
        """
        if self._on_status_update:
            self._on_status_update(state)

    def on_error(self, error: str, *, context: str | None = None) -> None:
        """Write error with severity classification and suggestion.

        Args:
            error: Error message.
            context: Optional error context.
        """
        if not self._on_panel_write:
            return

        # Classify severity
        severity = self._classify_error_severity(error, context)

        # Choose icon and color based on severity
        icon_category = {
            "critical": "critical",
            "warning": "warning",
            "error": "error",
        }.get(severity, "error")

        icon = get_icon(icon_category)
        color = DOT_COLORS[icon_category]

        # Create error line
        error_line = Text()
        error_line.append(f"{icon} ", style=color)

        if context:
            error_line.append(f"[{context}] ", style="dim red")

        error_line.append(error[:80], style=color)  # RFC-0020 compliance: 80 char limit

        self._on_panel_write(error_line)

        # Add suggestion if available
        suggestion = self._get_error_suggestion(error, context)
        if suggestion:
            suggestion_line = Text()
            suggestion_line.append("  💡 ", style="dim cyan")
            suggestion_line.append("Suggestion: ", style="dim italic")
            suggestion_line.append(suggestion, style="dim cyan")
            self._on_panel_write(suggestion_line)

    def on_progress_event(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        namespace: tuple[str, ...],
    ) -> None:
        """Write progress event to panel with two-level tree structure.

        Args:
            event_type: Event type string.
            data: Event payload.
            namespace: Subagent namespace.
        """
        if not self._on_panel_write:
            return

        # Build top-level summary from registry template
        summary = self._build_event_summary(event_type, data)
        if not summary:
            return

        # Determine color based on namespace
        color = DOT_COLORS.get("subagent", "magenta") if namespace else DOT_COLORS.get("protocol", "dim")

        # Create simple one-level display (consistent with CLI)
        self._on_panel_write(make_dot_line(color, summary))

    def _build_event_summary(self, event_type: str, data: dict[str, Any]) -> str:
        """Build human-readable summary for event using registry template.

        Args:
            event_type: Event type string.
            data: Event payload.

        Returns:
            Human-readable summary or empty string.
        """
        # Delegate to shared logic
        return build_event_summary(event_type, data)

    def on_plan_created(self, plan: Plan) -> None:  # noqa: ARG002
        """Handle plan creation.

        Args:
            plan: Created plan object.
        """
        if self._on_plan_refresh:
            self._on_plan_refresh()

    def on_plan_step_started(self, step_id: str, description: str) -> None:  # noqa: ARG002
        """Handle plan step start.

        Args:
            step_id: Step identifier.
            description: Step description.
        """
        if self._on_plan_refresh:
            self._on_plan_refresh()

    def on_plan_step_completed(
        self,
        step_id: str,  # noqa: ARG002
        success: bool,  # noqa: ARG002, FBT001
        duration_ms: int,  # noqa: ARG002
    ) -> None:
        """Handle plan step completion.

        Args:
            step_id: Step identifier.
            success: True if step succeeded.
            duration_ms: Step duration in milliseconds.
        """
        if self._on_plan_refresh:
            self._on_plan_refresh()

    def on_turn_end(self) -> None:
        """Finalize streaming on turn end."""
        if self._state.streaming_active:
            self._state.streaming_active = False
            self._state.last_assistant_output = self._state.streaming_text_buffer
            self._state.streaming_text_buffer = ""
        # Reset deduplication flag for next turn
        self._state.final_response_emitted = False

    def _is_long_running_tool(self, name: str) -> bool:
        """Detect if tool typically takes >5 seconds.

        Args:
            name: Tool name.

        Returns:
            True if tool is known to be long-running.
        """
        long_running_tools = {
            "web_search",
            "research_subagent",
            "browser_subagent",
            "claude_subagent",
            "execute_bash_command",
        }
        return any(lr in name for lr in long_running_tools)

    def _classify_error_severity(self, error: str, context: str | None) -> str:
        """Classify error severity for appropriate display.

        Args:
            error: Error message.
            context: Error context (e.g., "daemon", "thread", "tool_execution").

        Returns:
            Severity level: "critical", "warning", or "error".
        """
        error_lower = error.lower()

        # Critical: system failures or daemon errors
        if context == "daemon" or any(term in error_lower for term in ["connection", "socket", "fatal", "critical"]):
            return "critical"

        # Warning: recoverable issues
        if any(term in error_lower for term in ["retry", "timeout", "warning", "deprecated"]):
            return "warning"

        return "error"

    def _get_error_suggestion(self, error: str, context: str | None) -> str | None:
        """Provide actionable suggestion for common errors.

        Args:
            error: Error message.
            context: Error context.

        Returns:
            Suggestion string or None.
        """
        error_lower = error.lower()

        if "connection" in error_lower:
            return "Check if daemon is running: soothe daemon status"

        if "timeout" in error_lower:
            return "Operation may take longer. Try again or check logs."

        if "permission" in error_lower:
            return "Check file permissions or run with appropriate access."

        if "not found" in error_lower and context == "thread":
            return "Thread may have expired. Use 'soothe thread list' to see available threads."

        return None
