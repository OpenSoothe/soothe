"""TUI renderer implementing RendererProtocol for Rich panel output.

This module provides the TuiRenderer class that outputs events to
Rich panel widgets with streaming support and visual styling.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from rich.console import RenderableType
from rich.text import Text

from soothe.tools.display_names import get_tool_display_name
from soothe.ux.shared.event_formatter import build_event_summary
from soothe.ux.shared.message_processing import format_tool_call_args
from soothe.ux.shared.presentation_engine import PresentationEngine
from soothe.ux.shared.tui_trace_log import log_tui_trace
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

# Tool/subgraph streams often use empty namespace → EventProcessor marks them is_main=True.
# The parent graph then streams the same prose again as main; dedup by prefix vs last snapshot.
_DUP_SNAPSHOT_MIN_CHARS = 400
_DUP_PREFIX_COMPARE_CHARS = 700
# Minimum matching prefix length to consider two streams as duplicates
_DUP_MIN_MATCH_LEN = 80
# Minimum normalized subagent length before substring embed-dedup applies (IG-130)
_EMBED_DEDUP_SNAPSHOT_MIN = 400
# Strip block-drawing chars (e.g. ▂) that can leak into the panel buffer and break prefix match.
_BLOCK_DRAWING_RE = re.compile(r"[\u2580-\u259F]+")

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

    # Last completed assistant stream (raw body, no "[subagent] " prefix) for duplicate detection
    last_stream_snapshot: str = ""
    last_stream_role: str | None = None  # "main" | "subagent"
    current_stream_role: str | None = None
    suppress_duplicate_main_stream: bool = False
    # Subagent body used to suppress main streams that re-embed the same text (IG-130)
    subagent_embed_dedup_text: str = ""


class TuiRenderer:
    """TUI renderer for Rich panel widgets.

    Implements RendererProtocol callbacks for TUI mode:
    - Assistant text -> Conversation panel (streaming with live updates)
    - Tool calls/results -> Panel blocks with tree format
    - Progress events -> Panel with colored dots
    - Plan updates -> Refresh plan tree widget

    Usage:
        presentation = PresentationEngine()
        renderer = TuiRenderer(
            on_panel_write=panel.append_entry,
            on_panel_update_last=panel.update_last_entry,
            on_status_update=update_status_bar,
            on_plan_refresh=refresh_plan_tree,
            presentation_engine=presentation,
        )
        processor = EventProcessor(
            renderer, verbosity="normal", presentation_engine=presentation
        )
    """

    def __init__(
        self,
        *,
        on_panel_write: PanelWriteCallback = None,
        on_panel_update_last: PanelUpdateCallback = None,
        on_status_update: StatusUpdateCallback = None,
        on_plan_refresh: PlanRefreshCallback = None,
        presentation_engine: PresentationEngine | None = None,
        tui_debug: bool = False,
    ) -> None:
        """Initialize TUI renderer.

        Args:
            on_panel_write: Callback to append to conversation panel.
            on_panel_update_last: Callback to update last panel entry.
            on_status_update: Callback for status bar updates.
            on_plan_refresh: Callback to refresh plan tree widget.
            presentation_engine: Shared engine with EventProcessor (RFC-502).
            tui_debug: When True, emit INFO logs on logger ``soothe.ux.tui.trace`` (IG-129).
        """
        self._on_panel_write = on_panel_write
        self._on_panel_update_last = on_panel_update_last
        self._on_status_update = on_status_update
        self._on_plan_refresh = on_plan_refresh
        self._presentation = presentation_engine or PresentationEngine()
        self._state = TuiRendererState()
        self._tui_debug = tui_debug

    def _rebind_presentation(self, engine: PresentationEngine) -> None:
        """Attach a shared presentation engine (used by EventProcessor wiring)."""
        self._presentation = engine

    @property
    def presentation_engine(self) -> PresentationEngine:
        """Shared presentation policy with EventProcessor."""
        return self._presentation

    @property
    def last_assistant_output(self) -> str:
        """Get last assistant output for copy-to-clipboard."""
        return self._state.last_assistant_output

    @property
    def streaming_active(self) -> bool:
        """Whether currently streaming assistant text."""
        return self._state.streaming_active

    def on_assistant_text(
        self,
        text: str,
        *,
        is_main: bool,
        is_streaming: bool,
    ) -> None:
        """Stream assistant text to panel.

        Args:
            text: Text content to display.
            is_main: True if from main agent.
            is_streaming: True if partial chunk.
        """
        log_tui_trace(
            tui_debug=self._tui_debug,
            event="renderer.assistant_text",
            is_main=is_main,
            is_streaming=is_streaming,
            chars=len(text),
        )
        role = "main" if is_main else "subagent"
        self._stream_assistant_panel_text(text, role=role, is_streaming=is_streaming)

    @staticmethod
    def _normalize_for_dedup_compare(text: str, max_chars: int) -> str:
        """Normalize assistant text for main-echo duplicate detection (whitespace + UI noise)."""
        clipped = text[:max_chars]
        clipped = _BLOCK_DRAWING_RE.sub("", clipped)
        return " ".join(clipped.split())

    def _persist_stream_snapshot_from_buffer(self) -> None:
        """Store completed stream text before buffer clear (tool call / turn end)."""
        raw = (self._state.streaming_text_buffer or "").strip()
        if raw:
            self._state.last_stream_snapshot = raw
            self._state.last_stream_role = self._state.current_stream_role or "main"
            role = self._state.last_stream_role or "main"
            if role == "subagent" and len(raw) >= _EMBED_DEDUP_SNAPSHOT_MIN:
                self._state.subagent_embed_dedup_text = raw

    def _stream_assistant_panel_text(self, text: str, *, role: str, is_streaming: bool) -> None:
        """Stream assistant or subagent text with live updates (full body, IG-128).

        Subagent output was previously capped at 80 characters per chunk, which made
        long translations unreadable. Use the same buffer/update-last path as main.

        Args:
            text: Text chunk to append.
            role: ``main`` or ``subagent``.
            is_streaming: LangChain chunk vs final message.
        """
        if self._state.suppress_duplicate_main_stream:
            log_tui_trace(
                tui_debug=self._tui_debug,
                event="renderer.assistant_text_suppressed",
                is_streaming=is_streaming,
            )
            if not is_streaming:
                self._state.suppress_duplicate_main_stream = False
            return

        embed_snap = (self._state.subagent_embed_dedup_text or "").strip()
        if role == "main" and embed_snap and len(embed_snap) >= _EMBED_DEDUP_SNAPSHOT_MIN:
            cap = min(len(embed_snap) + 400, 120_000)
            n_snap = self._normalize_for_dedup_compare(embed_snap, min(len(embed_snap), 8000))
            n_buf = self._normalize_for_dedup_compare(
                (self._state.streaming_text_buffer + text)[:cap],
                cap,
            )
            if len(n_snap) >= _EMBED_DEDUP_SNAPSHOT_MIN and n_snap in n_buf:
                log_tui_trace(
                    tui_debug=self._tui_debug,
                    event="renderer.embed_duplicate_main_suppressed",
                    snap_chars=len(embed_snap),
                )
                if not is_streaming:
                    self._state.subagent_embed_dedup_text = ""
                return

        color_key = "assistant" if role == "main" else "subagent"
        prefix = "" if role == "main" else "[subagent] "

        if (
            not self._state.streaming_active
            and role == "main"
            and len(self._state.last_stream_snapshot) >= _DUP_SNAPSHOT_MIN_CHARS
        ):
            head = self._normalize_for_dedup_compare(
                text.lstrip(),
                _DUP_PREFIX_COMPARE_CHARS,
            )
            snap = self._normalize_for_dedup_compare(
                self._state.last_stream_snapshot.lstrip(),
                _DUP_PREFIX_COMPARE_CHARS,
            )
            n = min(len(head), len(snap), _DUP_PREFIX_COMPARE_CHARS)
            if n >= _DUP_MIN_MATCH_LEN and head[:n] == snap[:n]:
                log_tui_trace(
                    tui_debug=self._tui_debug,
                    event="renderer.duplicate_main_stream_detected",
                    compare_n=n,
                    snap_chars=len(self._state.last_stream_snapshot),
                )
                self._state.suppress_duplicate_main_stream = True
                if not is_streaming:
                    self._state.suppress_duplicate_main_stream = False
                return

        self._state.streaming_text_buffer += text
        body = prefix + self._state.streaming_text_buffer
        display_text = make_dot_line(DOT_COLORS[color_key], body)

        if not self._state.streaming_active:
            self._state.streaming_active = True
            self._state.current_stream_role = role
            if self._on_panel_write:
                self._on_panel_write(display_text)
            else:
                logger.warning("TuiRenderer: on_panel_write is None, cannot write first chunk")
        elif self._on_panel_update_last:
            self._on_panel_update_last(display_text)
        elif self._on_panel_write:
            logger.warning("TuiRenderer: on_panel_update_last is None, falling back to write")
            self._on_panel_write(display_text)

        # Persist snapshot when this assistant message completes. Subagent streams often end
        # without another on_tool_call before the main graph echoes the same text; without
        # this, last_stream_snapshot still held the main pre-tool buffer (IG-128 TUI dedup).
        if not is_streaming and self._state.streaming_active:
            log_tui_trace(
                tui_debug=self._tui_debug,
                event="renderer.stream_finalize",
                role=role,
                buf_chars=len(self._state.streaming_text_buffer),
            )
            self._persist_stream_snapshot_from_buffer()
            self._state.last_assistant_output = self._state.streaming_text_buffer
            self._state.streaming_active = False
            self._state.streaming_text_buffer = ""
            self._state.current_stream_role = None
            if role == "main":
                self._state.subagent_embed_dedup_text = ""

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
        log_tui_trace(
            tui_debug=self._tui_debug,
            event="renderer.tool_call",
            name=name,
            tool_call_id=tool_call_id,
        )
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

        # Finalize streaming before tool block (retain snapshot for main/subagent dedup)
        if self._state.streaming_active:
            self._persist_stream_snapshot_from_buffer()
            self._state.last_assistant_output = self._state.streaming_text_buffer
            self._state.streaming_active = False
            self._state.streaming_text_buffer = ""
            self._state.current_stream_role = None

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
        log_tui_trace(
            tui_debug=self._tui_debug,
            event="renderer.tool_result",
            tool_call_id=tool_call_id,
            is_error=is_error,
            result_chars=len(result),
        )
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

        brief = self._presentation.summarize_tool_result(result)

        # Create result line
        result_line = Text()
        result_line.append("  └ ", style="dim")
        result_line.append(icon + " ", style=color)
        result_line.append(brief[:80], style="dim")  # RFC-0020 compliance: 80 char limit

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

        color = self._progress_event_dot_color(event_type, data, namespace)

        # Create simple one-level display (consistent with CLI)
        self._on_panel_write(make_dot_line(color, summary))

    def _progress_event_dot_color(
        self,
        event_type: str,
        data: dict[str, Any],
        namespace: tuple[str, ...],
    ) -> str:
        """Prefix color for progress lines (success completions → green, not protocol/subagent)."""
        if event_type == "soothe.agentic.loop.completed":
            status = str(data.get("status", "done")).lower()
            return DOT_COLORS["plan_step_done"] if status == "done" else DOT_COLORS["protocol"]
        if event_type == "soothe.cognition.loop_agent.reason":
            status = str(data.get("status", "")).lower()
            if status == "done":
                return DOT_COLORS["plan_step_done"]
            if status == "replan":
                return DOT_COLORS["warning"]
            return DOT_COLORS["iteration"]
        if event_type == "soothe.agentic.step.completed" and data.get("success"):
            return DOT_COLORS["plan_step_done"]
        if event_type == "soothe.agentic.step.started":
            return DOT_COLORS["plan_step_active"]
        if namespace:
            return DOT_COLORS.get("subagent", "magenta")
        return DOT_COLORS.get("protocol", "dim")

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
        log_tui_trace(
            tui_debug=self._tui_debug,
            event="renderer.turn_end",
            streaming_active=self._state.streaming_active,
        )
        if self._state.streaming_active:
            self._persist_stream_snapshot_from_buffer()
            self._state.last_assistant_output = self._state.streaming_text_buffer
            self._state.streaming_active = False
            self._state.streaming_text_buffer = ""
            self._state.current_stream_role = None
        self._state.suppress_duplicate_main_stream = False
        self._state.subagent_embed_dedup_text = ""

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
