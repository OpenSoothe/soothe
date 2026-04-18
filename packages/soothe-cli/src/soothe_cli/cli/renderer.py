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

from soothe_sdk.utils import get_tool_display_name
from soothe_sdk.verbosity import VerbosityTier

from soothe_cli.cli.stream import DisplayLine, StreamDisplayPipeline
from soothe_cli.cli.utils import make_tool_block
from soothe_cli.shared.display_policy import VerbosityLevel, normalize_verbosity
from soothe_cli.shared.message_processing import format_tool_call_args
from soothe_cli.shared.presentation_engine import PresentationEngine
from soothe_cli.shared.suppression_state import SuppressionState

if TYPE_CHECKING:
    from soothe_sdk.client.schemas import Plan


@dataclass
class CliRendererState:
    """CLI-specific display state."""

    # Track if stdout needs newline before stderr output
    needs_stdout_newline: bool = False

    # Track if stderr was just written (to add spacing before next stdout)
    stderr_just_written: bool = False

    # Multi-step/agentic suppression state (IG-143)
    suppression: SuppressionState = field(default_factory=SuppressionState)

    # Track current plan for status display
    current_plan: Plan | None = None

    # Track tool call start times for duration display (RFC-0020)
    tool_call_start_times: dict[str, float] = field(default_factory=dict)

    # After LLM text on stdout, next stderr icon block gets one leading blank line
    stderr_blank_before_next_icon_block: bool = False


class CliRenderer:
    """CLI renderer for headless stdout/stderr output.

    Implements RendererProtocol callbacks for CLI mode:
    - Assistant text -> stdout (streaming)
    - Tool calls/results -> stderr (flat stream)
    - Progress events -> stderr via StreamDisplayPipeline
    - Errors -> stderr

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
        return self._state.suppression.full_response

    @property
    def multi_step_active(self) -> bool:
        """Whether multi-step plan is active."""
        return self._state.suppression.multi_step_active

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

    def _write_stdout_final_report(self, text: str) -> None:
        """Write aggregated final answer to stdout (multi-step headless mode only)."""
        stripped = text.strip()
        if not stripped:
            return

        self._state.suppression.full_response.append(stripped)

        # Add newline before final report if stderr was just written (goal completion)
        if self._state.stderr_just_written:
            sys.stdout.write("\n")
            self._state.stderr_just_written = False

        sys.stdout.write(stripped)
        if not stripped.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
        self._state.needs_stdout_newline = True
        self._state.stderr_blank_before_next_icon_block = True
        self._presentation.mark_final_answer_locked()

    def on_assistant_text(
        self,
        text: str,
        *,
        is_main: bool,
        is_streaming: bool,  # noqa: ARG002
    ) -> None:
        """Write assistant text to stdout.

        HARD SUPPRESS during multi-step execution to prevent intermediate
        LLM response text from flooding output (IG-143).

        Args:
            text: Text content to display.
            is_main: True if from main agent.
            is_streaming: True if partial chunk.
        """
        if not is_main:
            return  # Subagent text not shown in CLI headless mode

        # HARD BLOCK: No text during multi-step execution (IG-143)
        if self._state.suppression.should_suppress_output():
            # Accumulate for final report instead
            self._state.suppression.accumulate_text(text)
            return

        # Emit only on final iteration (after flags cleared)
        self._state.suppression.full_response.append(text)

        if self._state.stderr_just_written:
            self._state.stderr_just_written = False

        # LLM stream: do not inject extra blank lines (spacing before icon stderr
        # is handled in _stderr_begin_icon_block when progress resumes).
        sys.stdout.write(text)
        sys.stdout.flush()
        self._state.needs_stdout_newline = True
        self._state.stderr_blank_before_next_icon_block = True

    def on_tool_call(
        self,
        name: str,
        args: dict[str, Any],
        tool_call_id: str,
        *,
        is_main: bool,  # noqa: ARG002
    ) -> None:
        """Write tool call to stderr as a flat stream line.

        Args:
            name: Tool name.
            args: Parsed arguments (may contain _raw for fallback).
            tool_call_id: Tool call identifier.
            is_main: True if from main agent.
        """
        if not self._presentation.tier_visible(VerbosityTier.NORMAL, self._verbosity):
            return

        # Multi-step / agentic suppression applies to assistant stdout only (IG-143).
        # Tool calls and results still stream to stderr at normal+ verbosity so headless
        # runs show the same tool activity as the TUI.

        self._stderr_begin_icon_block()

        display_name = get_tool_display_name(name)

        # Pass args directly, including any _raw fallback
        args_str = format_tool_call_args(name, {"args": args, "_raw": args.get("_raw", "")})

        # Use display helper for consistency with TUI (RFC-0020 Principle 5)
        tool_block = make_tool_block(display_name, args_str, status="running")

        # Track start time for duration display (RFC-0020)
        if tool_call_id:
            self._state.tool_call_start_times[tool_call_id] = time.time()

        sys.stderr.write(f"{tool_block}\n")
        sys.stderr.flush()
        # Mark that stderr was just written
        self._state.stderr_just_written = True

    def on_tool_result(
        self,
        name: str,  # noqa: ARG002
        result: str,
        tool_call_id: str,
        *,
        is_error: bool,
        is_main: bool,  # noqa: ARG002
    ) -> None:
        """Write tool result to stderr as a flat stream line with duration.

        Args:
            name: Tool name.
            result: Result content (truncated).
            tool_call_id: Tool call identifier.
            is_error: True if result indicates error.
            is_main: True if from main agent.
        """
        if not self._presentation.tier_visible(VerbosityTier.NORMAL, self._verbosity):
            return

        # See on_tool_call: do not suppress stderr tool results during multi-step runs.

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

        sys.stderr.write(result_line + "\n")
        sys.stderr.flush()

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

    def on_progress_event(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        namespace: tuple[str, ...],  # noqa: ARG002
    ) -> None:
        """Write progress event to stderr using StreamDisplayPipeline.

        Args:
            event_type: Event type string.
            data: Event payload.
            namespace: Subagent namespace.
        """
        # Track suppression state from event (IG-143)
        final_stdout = self._state.suppression.track_from_event(event_type, data)

        payload = dict(data)
        payload.pop("final_stdout_message", None)

        # Build event dict for pipeline
        event = {"type": event_type, **payload}
        lines = self._pipeline.process(event)
        self.write_lines(lines)

        # Emit final report on loop completion (IG-143)
        if self._state.suppression.should_emit_final_report(event_type, final_stdout):
            response = self._state.suppression.get_final_response(final_stdout)
            self._write_stdout_final_report(response)

    def on_plan_created(self, plan: Plan) -> None:
        """Write plan creation to stderr.

        Args:
            plan: Created plan object.
        """
        self._state.current_plan = plan
        self._state.suppression.track_from_plan(len(plan.steps))

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
        """Finalize output on turn end.

        If multi_step_active was suppressing output, flush the accumulated
        response to stdout now that the plan is complete.
        """
        # Capture state BEFORE resetting
        was_multi_step = self._state.suppression.multi_step_active
        accumulated_response = self._state.suppression.full_response

        # Reset state for next turn FIRST (before output logic)
        self._state.needs_stdout_newline = False
        self._state.suppression.reset_turn()

        # Multi-step mode intentionally suppresses step body output in headless CLI.
        # For single-step mode, keep existing newline flush behavior.
        if (not was_multi_step) and accumulated_response:
            sys.stdout.write("\n")
            sys.stdout.flush()

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
