"""CLI renderer implementing RendererProtocol for headless output.

This module provides the CliRenderer class that outputs events to
stdout (assistant text) and stderr (progress/tool events).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from soothe.tools.display_names import get_tool_display_name
from soothe.ux.core.display_policy import VerbosityLevel
from soothe.ux.core.message_processing import format_tool_call_args
from soothe.ux.core.progress_verbosity import should_show

if TYPE_CHECKING:
    from soothe.protocols.planner import Plan


@dataclass
class CliRendererState:
    """CLI-specific display state."""

    # Track if stdout needs newline before stderr output
    needs_stdout_newline: bool = False

    # Suppress step text during multi-step plans
    multi_step_active: bool = False

    # Accumulated response text
    full_response: list[str] = field(default_factory=list)

    # Track current plan for status display
    current_plan: Plan | None = None


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
        self._verbosity = verbosity
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
            sys.stdout.write(text)
            sys.stdout.flush()
            self._state.needs_stdout_newline = True

    def on_tool_call(
        self,
        name: str,
        args: dict[str, Any],
        tool_call_id: str,  # noqa: ARG002
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
        if not should_show("tool_activity", self._verbosity):
            return

        self._ensure_newline()

        display_name = get_tool_display_name(name)
        args_str = format_tool_call_args(name, {"args": args})

        # Add separator newline before event
        sys.stderr.write(f"\n⚙ {display_name}{args_str}\n")
        sys.stderr.flush()

    def on_tool_result(
        self,
        name: str,  # noqa: ARG002
        result: str,
        tool_call_id: str,  # noqa: ARG002
        *,
        is_error: bool,
        is_main: bool,  # noqa: ARG002
    ) -> None:
        """Write tool result to stderr in tree format.

        Args:
            name: Tool name.
            result: Result content (truncated).
            tool_call_id: Tool call identifier.
            is_error: True if result indicates error.
            is_main: True if from main agent.
        """
        if not should_show("tool_activity", self._verbosity):
            return

        self._ensure_newline()

        icon = "✗" if is_error else "✓"
        sys.stderr.write(f"  └ {icon} {result}\n")
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
        # Add separator newline before error
        sys.stderr.write(f"\n{prefix}ERROR: {error}\n")
        sys.stderr.flush()

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
        # Add separator newline before event
        sys.stderr.write("\n")
        render_progress_event(event_type, data, current_plan=self._state.current_plan)

    def on_plan_created(self, plan: Plan) -> None:
        """Write plan creation to stderr.

        Args:
            plan: Created plan object.
        """
        self._ensure_newline()
        self._state.current_plan = plan
        self._state.multi_step_active = len(plan.steps) > 1
        # Add separator newline and display plan with steps
        sys.stderr.write(f"\n[plan] ● {plan.goal} ({len(plan.steps)} steps)\n")
        for step in plan.steps:
            sys.stderr.write(f"  ├ {step.id}: {step.description} [pending]\n")
        sys.stderr.flush()

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

        # Status indicators
        status_icons = {
            "pending": "○",
            "in_progress": "◐",
            "completed": "✓",
            "failed": "✗",
        }

        # Add separator and header
        sys.stderr.write(f"\n[plan] ● {plan.goal}\n")
        for step in plan.steps:
            icon = status_icons.get(step.status, "○")
            sys.stderr.write(f"  ├ {icon} {step.id}: {step.description}\n")
        sys.stderr.flush()

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
