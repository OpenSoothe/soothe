"""CLI renderer implementing RendererProtocol for headless output.

This module provides the CliRenderer class that outputs events to
stdout (assistant text) and stderr (progress/tool events).
Uses StreamDisplayPipeline for RFC-0020 compliant progress display.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from soothe_sdk.core.verbosity import VerbosityTier
from soothe_sdk.utils import get_tool_display_name

from soothe_cli.cli.stream import DisplayLine, StreamDisplayPipeline
from soothe_cli.cli.task_scope_display import format_task_scope_prefix
from soothe_cli.shared.display_policy import VerbosityLevel, normalize_verbosity
from soothe_cli.shared.explore_task_display import format_explore_task_json_blob_for_display
from soothe_cli.shared.message_processing import format_tool_call_args
from soothe_cli.shared.presentation_engine import PresentationEngine
from soothe_cli.shared.renderer_base import RendererBase

if TYPE_CHECKING:
    from soothe_sdk.client.schemas import Plan


@dataclass
class CliRendererState:
    """CLI-specific display state."""

    # Track if stdout needs newline before stderr output
    needs_stdout_newline: bool = False

    # Track if stderr was just written (to add spacing before next stdout)
    stderr_just_written: bool = False

    # Per-turn assistant output accumulation for diagnostics/tests.
    full_response: list[str] = field(default_factory=list)

    # Track current plan for status display
    current_plan: Plan | None = None

    # Track tool call start times for duration display (RFC-0020)
    tool_call_start_times: dict[str, float] = field(default_factory=dict)

    # Buffer tool-call line text until result arrives for single-line rendering.
    pending_tool_call_lines: dict[str, str] = field(default_factory=dict)

    # After LLM text on stdout, next stderr icon block gets one leading blank line
    stderr_blank_before_next_icon_block: bool = False

    # Main-agent stdout: prepend ● before the next non-empty assistant chunk (IG-331).
    assistant_leading_bullet_pending: bool = True

    # Explore Task subgraph: buffer streamed JSON; emit one simplified line on final (IG-311).
    explore_task_json_buffer: str = ""


class CliRenderer(RendererBase):
    """CLI renderer for headless stdout/stderr output.

    Implements RendererProtocol callbacks for CLI mode:
    - Assistant text -> stdout (streaming)
    - Tool calls/results -> stderr (flat stream)
    - Progress events -> stderr via StreamDisplayPipeline
    - Errors -> stderr

    Inherits from RendererBase for unified text repair logic.

    Spacing: Soothe-originated stderr lines (icons from the pipeline, tools, results,
    errors) call `_stderr_begin_icon_block()`, which inserts one blank stderr line only
    after LLM text was written to stdout, so icon blocks separate from answers without
    extra blank lines inside the LLM stream or between consecutive stderr lines.

    Usage:
        renderer = CliRenderer(verbosity="normal")
        processor = EventProcessor(renderer, verbosity="normal")
    """

    def __init__(
        self,
        *,
        verbosity: VerbosityLevel = "normal",
        presentation_engine: PresentationEngine | None = None,
    ) -> None:
        """Initialize CLI renderer.

        Args:
            verbosity: Progress visibility level.
            presentation_engine: Shared presentation engine (optional).
        """
        super().__init__()
        self._verbosity = normalize_verbosity(verbosity)
        self._state = CliRendererState()
        self._presentation = presentation_engine or PresentationEngine()
        self._pipeline = StreamDisplayPipeline(
            verbosity=verbosity,
            presentation_engine=self._presentation,
        )

    def _rebind_presentation(self, engine: PresentationEngine) -> None:
        """Attach a shared presentation engine (used by EventProcessor wiring)."""
        self._presentation = engine
        self._pipeline = StreamDisplayPipeline(
            verbosity=self._verbosity,
            presentation_engine=engine,
        )

    @property
    def full_response(self) -> list[str]:
        """Get accumulated response text."""
        return self._state.full_response

    @property
    def presentation_engine(self) -> PresentationEngine:
        """Shared presentation policy used with StreamDisplayPipeline and EventProcessor."""
        return self._presentation

    def write_lines(self, lines: list[DisplayLine]) -> None:
        """Write display lines to stderr.

        Args:
            lines: List of DisplayLine objects to render.
        """
        if not lines:
            return

        self._stderr_begin_icon_block()

        for line in lines:
            sys.stderr.write(line.format() + "\n")

        sys.stderr.flush()
        self._state.stderr_just_written = True
        self._schedule_assistant_leading_bullet()

    def _schedule_assistant_leading_bullet(self) -> None:
        """Next main-agent stdout assistant segment should start with ● (⚙ when Task subgraph)."""
        self._state.assistant_leading_bullet_pending = True

    def on_assistant_text(
        self,
        text: str,
        *,
        is_main: bool,
        is_streaming: bool,
        task_scope: tuple[str, str] | None = None,
    ) -> None:
        """Write assistant text to stdout.

        Write assistant text directly. Daemon-side output contract decides
        which assistant text reaches clients.

        Args:
            text: Text content to display.
            is_main: True if from main agent.
            is_streaming: True if partial chunk.
            task_scope: ``(task_tool_call_id, subagent_type)`` for Task subgraph prose.
        """
        if not is_main:
            if not task_scope:
                return

        effective_streaming = is_streaming
        explore_task = bool(task_scope and task_scope[1] == "explore")
        if explore_task:
            chunk_text = text if is_streaming else self.repair_concatenated_output(text)
            if is_streaming:
                self._state.explore_task_json_buffer += chunk_text
                return
            combined = self._state.explore_task_json_buffer + chunk_text
            self._state.explore_task_json_buffer = ""
            payload = format_explore_task_json_blob_for_display(combined)
            effective_streaming = False
            if not payload.strip():
                self._schedule_assistant_leading_bullet()
                return
        else:
            payload = text if is_streaming else self.repair_concatenated_output(text)

        if self._state.explore_task_json_buffer and not explore_task:
            # Defensive: leftover explore buffer when subagent type switched mid-turn.
            self._state.explore_task_json_buffer = ""

        if payload and self._state.assistant_leading_bullet_pending:
            if task_scope and not effective_streaming:
                tcid, st = task_scope
                payload = "⚙ " + format_task_scope_prefix(tcid, st) + " " + payload.strip()
            else:
                if task_scope:
                    tcid, st = task_scope
                    lead = f"⚙ {format_task_scope_prefix(tcid, st)} "
                else:
                    lead = "● "
                payload = lead + payload
            self._state.assistant_leading_bullet_pending = False

        self._state.full_response.append(payload)

        if self._state.stderr_just_written:
            self._state.stderr_just_written = False

        # LLM stream: do not inject extra blank lines (spacing before icon stderr
        # is handled in _stderr_begin_icon_block when progress resumes).
        sys.stdout.write(payload)
        sys.stdout.flush()
        self._state.needs_stdout_newline = True
        self._state.stderr_blank_before_next_icon_block = True

        if not effective_streaming:
            self._schedule_assistant_leading_bullet()

    def on_streaming_output(
        self,
        event_type: str,
        text: str,
        *,
        is_chunk: bool,
        namespace: tuple[str, ...],
    ) -> None:
        """Handle streaming output from unified framework (RFC-614).

        Default implementation: delegate to on_assistant_text.
        CLI renderer treats all streaming output as assistant text.

        Args:
            event_type: Event type string.
            text: Text content (may be chunk or final).
            is_chunk: True if partial chunk, False if final.
            namespace: Namespace tuple for stream context (ignored in CLI headless mode).
        """
        # Delegate to on_assistant_text for unified display
        self.on_assistant_text(text, is_main=True, is_streaming=is_chunk)

    def on_tool_call(
        self,
        name: str,
        args: dict[str, Any],
        tool_call_id: str,
        *,
        is_main: bool,  # noqa: ARG002
        task_scope: tuple[str, str] | None = None,
    ) -> None:
        """Write tool call to stderr as a flat stream line.

        Args:
            name: Tool name.
            args: Parsed arguments (may contain _raw for fallback).
            tool_call_id: Tool call identifier.
            is_main: True if from main agent.
            task_scope: Parent Task scope for subgraph tools (IG-334).
        """
        if not self._presentation.tier_visible(VerbosityTier.NORMAL, self._verbosity):
            return

        self._stderr_begin_icon_block()

        display_name = get_tool_display_name(name)

        # Pass args directly, including any _raw fallback
        args_str = format_tool_call_args(name, {"args": args, "_raw": args.get("_raw", "")})

        core = f"{display_name}({args_str})"
        if task_scope:
            tcid, st = task_scope
            core = f"{format_task_scope_prefix(tcid, st)} {core}"
        tool_block = f"⚙ {core}"

        # Track start time for duration display (RFC-0020)
        if tool_call_id:
            self._state.tool_call_start_times[tool_call_id] = time.time()
            self._state.pending_tool_call_lines[tool_call_id] = tool_block
            return

        # No stable ID means we cannot join with result later - keep old behavior.
        sys.stderr.write(f"{tool_block}\n")
        sys.stderr.flush()
        self._state.stderr_just_written = True
        self._schedule_assistant_leading_bullet()

    def on_tool_result(
        self,
        name: str,  # noqa: ARG002
        result: str,
        tool_call_id: str,
        *,
        is_error: bool,
        is_main: bool,  # noqa: ARG002
        task_scope: tuple[str, str] | None = None,
    ) -> None:
        """Write tool result to stderr as a flat stream line with duration.

        Args:
            name: Tool name.
            result: Result content (truncated).
            tool_call_id: Tool call identifier.
            is_error: True if result indicates error.
            is_main: True if from main agent.
            task_scope: Unused when joined with pending call line (IG-334).
        """
        if not self._presentation.tier_visible(VerbosityTier.NORMAL, self._verbosity):
            return

        self._stderr_begin_icon_block()

        # Calculate duration (RFC-0020)
        duration_ms = 0
        if tool_call_id and tool_call_id in self._state.tool_call_start_times:
            start_time = self._state.tool_call_start_times.pop(tool_call_id)
            duration_ms = int((time.time() - start_time) * 1000)

        # Note: extract_tool_brief() may already include ✓/✗ icon
        result = self._presentation.summarize_tool_result(result)
        result_stripped = result.lstrip()
        if result_stripped.startswith(("✓", "✗")):
            result_line = result
        else:
            icon = "✗" if is_error else "✓"
            result_line = f"{icon} {result}"
        if duration_ms > 0:
            result_line += f" ({duration_ms}ms)"

        combined_call_line: str | None = None
        if tool_call_id:
            combined_call_line = self._state.pending_tool_call_lines.pop(tool_call_id, None)

        if combined_call_line:
            result_line = f"{combined_call_line} -> {result_line}"
        elif task_scope:
            tcid, st = task_scope
            result_line = f"{format_task_scope_prefix(tcid, st)} -> {result_line}"

        sys.stderr.write(result_line + "\n")
        sys.stderr.flush()
        self._schedule_assistant_leading_bullet()

    def on_status_change(self, state: str) -> None:
        """Handle status changes.

        No-op for CLI - status tracked by event loop.

        Args:
            state: New daemon state.
        """

    def on_error(self, error: str, *, context: str | None = None) -> None:
        """Write error to stderr.

        Args:
            error: Error message.
            context: Optional error context.
        """
        self._stderr_begin_icon_block()
        prefix = f"[{context}] " if context else ""
        sys.stderr.write(f"{prefix}ERROR: {error}\n")
        sys.stderr.flush()
        # Mark that stderr was just written
        self._state.stderr_just_written = True
        self._schedule_assistant_leading_bullet()

    def on_progress_event(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        namespace: tuple[str, ...],
        task_scope: tuple[str, str] | None = None,
    ) -> None:
        """Write progress event to stderr using StreamDisplayPipeline.

        Args:
            event_type: Event type string.
            data: Event payload.
            namespace: Subagent namespace.
            task_scope: Parent Task delegation scope for subgraph progress (IG-334).
        """
        # Build event dict for pipeline
        event: dict[str, Any] = {"type": event_type, **data, "namespace": list(namespace)}
        if task_scope:
            event["task_scope"] = task_scope
        lines = self._pipeline.process(event)
        self.write_lines(lines)

    def on_plan_created(self, plan: Plan) -> None:
        """Write plan creation to stderr.

        Args:
            plan: Created plan object.
        """
        self._state.current_plan = plan

        # Use pipeline for consistent formatting
        event = {
            "type": "soothe.cognition.plan.creating",
            "goal": plan.goal,
            "steps": [{"id": s.id, "description": s.description} for s in plan.steps],
        }
        lines = self._pipeline.process(event)
        self.write_lines(lines)

    def on_plan_step_started(self, step_id: str, description: str) -> None:
        """Update plan state and show step header.

        Args:
            step_id: Step identifier.
            description: Step description.
        """
        # Update step status in current plan
        if self._state.current_plan:
            for step in self._state.current_plan.steps:
                if step.id == step_id:
                    step.status = "in_progress"
                    break

        # Use pipeline for consistent formatting
        event = {
            "type": "soothe.cognition.plan.step.started",
            "step_id": step_id,
            "description": description,
        }
        lines = self._pipeline.process(event)
        self.write_lines(lines)

    def on_plan_step_completed(
        self,
        step_id: str,
        success: bool,  # noqa: FBT001
        duration_ms: int,
    ) -> None:
        """Update plan state and show step completion.

        Args:
            step_id: Step identifier.
            success: True if step succeeded.
            duration_ms: Step duration in milliseconds.
        """
        # Update step status in current plan
        if self._state.current_plan:
            for step in self._state.current_plan.steps:
                if step.id == step_id:
                    step.status = "completed" if success else "failed"
                    break

        # Use pipeline for consistent formatting
        event = {
            "type": "soothe.cognition.plan.step.completed",
            "step_id": step_id,
            "success": success,
            "duration_ms": duration_ms,
        }
        lines = self._pipeline.process(event)
        self.write_lines(lines)

    def on_turn_end(self) -> None:
        """Finalize turn-local renderer state."""
        self._state.needs_stdout_newline = False
        self._state.full_response.clear()
        self._state.pending_tool_call_lines.clear()
        self._schedule_assistant_leading_bullet()

    def _stderr_begin_icon_block(self) -> None:
        """Prepare stderr for Soothe icon lines (progress, tools, tool results).

        Ensures stdout ends with a newline, then inserts one blank stderr line
        only after LLM content was written to stdout so icon streams stay visually
        separated without double-spacing consecutive stderr lines.
        """
        self._ensure_newline()
        if self._state.stderr_blank_before_next_icon_block:
            sys.stderr.write("\n")
            self._state.stderr_blank_before_next_icon_block = False

    def _ensure_newline(self) -> None:
        """Ensure stdout has newline before stderr output.

        This prevents stderr output from mixing into stdout lines.
        """
        if self._state.needs_stdout_newline:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._state.needs_stdout_newline = False
