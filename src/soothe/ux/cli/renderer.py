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

from soothe.foundation.verbosity_tier import VerbosityTier, should_show
from soothe.tools.display_names import get_tool_display_name
from soothe.ux.cli.stream import DisplayLine, StreamDisplayPipeline
from soothe.ux.cli.utils import make_tool_block
from soothe.ux.shared.display_policy import VerbosityLevel, normalize_verbosity
from soothe.ux.shared.message_processing import format_tool_call_args

if TYPE_CHECKING:
    from soothe.protocols.planner import Plan


@dataclass
class CliRendererState:
    """CLI-specific display state."""

    # Track if stdout needs newline before stderr output
    needs_stdout_newline: bool = False

    # Track if stderr was just written (to add spacing before next stdout)
    stderr_just_written: bool = False

    # Suppress step text during multi-step plans
    multi_step_active: bool = False

    # Accumulated response text
    full_response: list[str] = field(default_factory=list)

    # Track current plan for status display
    current_plan: Plan | None = None

    # Track tool call start times for duration display (RFC-0020)
    tool_call_start_times: dict[str, float] = field(default_factory=dict)

    # Track if final response was already emitted via custom event (deduplication)
    final_response_emitted: bool = False


class CliRenderer:
    """CLI renderer for headless stdout/stderr output.

    Implements RendererProtocol callbacks for CLI mode:
    - Assistant text -> stdout (streaming)
    - Tool calls/results -> stderr (tree format)
    - Progress events -> stderr via StreamDisplayPipeline
    - Errors -> stderr

    Usage:
        renderer = CliRenderer(verbosity="normal")
        processor = EventProcessor(renderer, verbosity="normal")
    """

    def __init__(self, *, verbosity: VerbosityLevel = "normal") -> None:
        """Initialize CLI renderer.

        Args:
            verbosity: Progress visibility level.
        """
        self._verbosity = normalize_verbosity(verbosity)
        self._state = CliRendererState()
        self._pipeline = StreamDisplayPipeline(verbosity=verbosity)

    @property
    def full_response(self) -> list[str]:
        """Get accumulated response text."""
        return self._state.full_response

    @property
    def multi_step_active(self) -> bool:
        """Whether multi-step plan is active."""
        return self._state.multi_step_active

    def mark_final_response_emitted(self) -> None:
        """Mark that final response was emitted via custom event.

        Prevents duplicate output when the same content comes through
        the AIMessage stream.
        """
        self._state.final_response_emitted = True

    def write_lines(self, lines: list[DisplayLine]) -> None:
        """Write display lines to stderr.

        Args:
            lines: List of DisplayLine objects to render.
        """
        if not lines:
            return

        self._ensure_newline()

        for line in lines:
            sys.stderr.write(line.format() + "\n")

        sys.stderr.flush()
        self._state.stderr_just_written = True

    def on_assistant_text(
        self,
        text: str,
        *,
        is_main: bool,
        is_streaming: bool,  # noqa: ARG002
    ) -> None:
        """Write assistant text to stdout.

        Args:
            text: Text content to display.
            is_main: True if from main agent.
            is_streaming: True if partial chunk.
        """
        if not is_main:
            return  # Subagent text not shown in CLI headless mode

        # Skip if final response was already emitted via custom event
        if self._state.final_response_emitted:
            return

        self._state.full_response.append(text)

        if not self._state.multi_step_active:
            # Capture stderr state before resetting
            had_stderr_output = self._state.stderr_just_written
            if had_stderr_output:
                self._state.stderr_just_written = False

            # Add spacing before assistant text only when:
            # - There was prior stderr output (progress/tool events need separation)
            # For streaming chunks after the first, just continue without extra newlines.
            if had_stderr_output:
                sys.stdout.write("\n\n")
            sys.stdout.write(text)
            sys.stdout.flush()
            self._state.needs_stdout_newline = True

    def on_tool_call(
        self,
        name: str,
        args: dict[str, Any],
        tool_call_id: str,
        *,
        is_main: bool,  # noqa: ARG002
    ) -> None:
        """Write tool call to stderr in tree format.

        Args:
            name: Tool name.
            args: Parsed arguments (may contain _raw for fallback).
            tool_call_id: Tool call identifier.
            is_main: True if from main agent.
        """
        if not should_show(VerbosityTier.NORMAL, self._verbosity):
            return

        self._ensure_newline()

        display_name = get_tool_display_name(name)

        # Pass args directly, including any _raw fallback
        args_str = format_tool_call_args(name, {"args": args, "_raw": args.get("_raw", "")})

        # Use display helper for consistency with TUI (RFC-0020 Principle 5)
        tool_block = make_tool_block(display_name, args_str, status="running")

        # Track start time for duration display (RFC-0020)
        if tool_call_id:
            self._state.tool_call_start_times[tool_call_id] = time.time()

        sys.stderr.write(f"\n{tool_block}\n")
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
        """Write tool result to stderr in tree format with duration.

        Args:
            name: Tool name.
            result: Result content (truncated).
            tool_call_id: Tool call identifier.
            is_error: True if result indicates error.
            is_main: True if from main agent.
        """
        if not should_show(VerbosityTier.NORMAL, self._verbosity):
            return

        self._ensure_newline()

        # Calculate duration (RFC-0020)
        duration_ms = 0
        if tool_call_id and tool_call_id in self._state.tool_call_start_times:
            start_time = self._state.tool_call_start_times.pop(tool_call_id)
            duration_ms = int((time.time() - start_time) * 1000)

        # Format as child line with duration (RFC-0020 two-level tree)
        # Note: extract_tool_brief() may already include ✓/✗ icon
        result_stripped = result.lstrip()
        if result_stripped.startswith(("✓", "✗")):
            # Result already has icon, don't add another
            result_line = f"  └ {result}"
        else:
            icon = "✗" if is_error else "✓"
            result_line = f"  └ {icon} {result}"
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
        self._ensure_newline()
        prefix = f"[{context}] " if context else ""
        sys.stderr.write(f"\n{prefix}ERROR: {error}\n")
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
        # Track multi-step state from agentic loop start
        if event_type == "soothe.agentic.loop.started" and data.get("max_iterations", 1) > 1:
            self._state.multi_step_active = True

        # Build event dict for pipeline
        event = {"type": event_type, **data}
        lines = self._pipeline.process(event)
        self.write_lines(lines)

    def on_plan_created(self, plan: Plan) -> None:
        """Write plan creation to stderr.

        Args:
            plan: Created plan object.
        """
        self._state.current_plan = plan
        self._state.multi_step_active = len(plan.steps) > 1

        # Use pipeline for consistent formatting
        event = {
            "type": "soothe.cognition.plan.created",
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
            "type": "soothe.cognition.plan.step_started",
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
            "type": "soothe.cognition.plan.step_completed",
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
        was_multi_step = self._state.multi_step_active
        accumulated_response = self._state.full_response

        # Reset state for next turn FIRST (before output logic)
        self._state.needs_stdout_newline = False
        self._state.multi_step_active = False
        self._state.full_response = []
        self._state.final_response_emitted = False

        # Output any accumulated response that was suppressed during multi-step plan
        # Use captured state, not current state (which is now reset)
        if was_multi_step and accumulated_response:
            # Add separation after stderr progress output
            sys.stdout.write("\n\n")
            # Output the accumulated response
            sys.stdout.write("".join(accumulated_response))
            sys.stdout.write("\n")
            sys.stdout.flush()
        elif accumulated_response:
            sys.stdout.write("\n")
            sys.stdout.flush()

    def _ensure_newline(self) -> None:
        """Ensure stdout has newline before stderr output.

        This prevents stderr output from mixing into stdout lines.
        """
        if self._state.needs_stdout_newline:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._state.needs_stdout_newline = False
