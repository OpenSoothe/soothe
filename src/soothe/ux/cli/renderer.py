"""CLI renderer implementing RendererProtocol for headless output.

This module provides the CliRenderer class that outputs events to
stdout (assistant text) and stderr (progress/tool events).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from soothe.core.verbosity_tier import VerbosityTier, should_show
from soothe.tools.display_names import get_tool_display_name
from soothe.ux.cli.utils import make_tool_block
from soothe.ux.core.display_policy import VerbosityLevel, normalize_verbosity
from soothe.ux.core.message_processing import format_tool_call_args

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


class CliRenderer:
    """CLI renderer for headless stdout/stderr output.

    Implements RendererProtocol callbacks for CLI mode:
    - Assistant text -> stdout (streaming)
    - Tool calls/results -> stderr (tree format)
    - Progress events -> stderr (bracketed format)
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

    @property
    def full_response(self) -> list[str]:
        """Get accumulated response text."""
        return self._state.full_response

    @property
    def multi_step_active(self) -> bool:
        """Whether multi-step plan is active."""
        return self._state.multi_step_active

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

        self._state.full_response.append(text)

        if not self._state.multi_step_active:
            if self._state.stderr_just_written:
                self._state.stderr_just_written = False

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
            args: Parsed arguments.
            tool_call_id: Tool call identifier.
            is_main: True if from main agent.
        """
        if not should_show(VerbosityTier.NORMAL, self._verbosity):
            return

        self._ensure_newline()

        display_name = get_tool_display_name(name)
        args_str = format_tool_call_args(name, {"args": args})

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
        """Write progress event to stderr using existing renderer.

        Args:
            event_type: Event type string.
            data: Event payload.
            namespace: Subagent namespace.
        """
        from soothe.ux.cli.progress import render_progress_event

        self._ensure_newline()
        sys.stderr.write("\n")
        render_progress_event(event_type, data, current_plan=self._state.current_plan)
        # Mark that stderr was just written
        self._state.stderr_just_written = True

    def on_plan_created(self, plan: Plan) -> None:
        """Write plan creation to stderr.

        Args:
            plan: Created plan object.
        """
        self._ensure_newline()
        self._state.current_plan = plan
        self._state.multi_step_active = len(plan.steps) > 1
        sys.stderr.write(f"\nPlan: {plan.goal}\n")
        sys.stderr.flush()
        # Mark that stderr was just written
        self._state.stderr_just_written = True

    def on_plan_step_started(self, step_id: str, _description: str) -> None:
        """Update plan state and show updated plan status.

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
            # Display updated plan status
            self._render_plan_update()

    def on_plan_step_completed(
        self,
        step_id: str,
        success: bool,  # noqa: FBT001
        _duration_ms: int,
    ) -> None:
        """Update plan state and show updated plan status.

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
            # Display updated plan status
            self._render_plan_update()

    def _render_plan_update(self) -> None:
        """Render the current plan with status indicators."""
        if not self._state.current_plan:
            return

        self._ensure_newline()
        plan = self._state.current_plan

        active_step = next((step for step in plan.steps if step.status == "in_progress"), None)
        completed_step = next((step for step in reversed(plan.steps) if step.status == "completed"), None)
        failed_step = next((step for step in reversed(plan.steps) if step.status == "failed"), None)

        if failed_step:
            sys.stderr.write(f"\nDone: {failed_step.description}\n")
        elif active_step:
            sys.stderr.write(f"\nPlan: {active_step.description}\n")
        elif completed_step:
            sys.stderr.write(f"\nDone: {completed_step.description}\n")
        sys.stderr.flush()
        # Mark that stderr was just written
        self._state.stderr_just_written = True

    def on_turn_end(self) -> None:
        """Finalize output on turn end."""
        if self._state.full_response:
            sys.stdout.write("\n")
            sys.stdout.flush()
        self._state.needs_stdout_newline = False

    def _ensure_newline(self) -> None:
        """Ensure stdout has newline before stderr output.

        This prevents stderr output from mixing into stdout lines.
        """
        if self._state.needs_stdout_newline:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._state.needs_stdout_newline = False
