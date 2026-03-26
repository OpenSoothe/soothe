"""CLI renderer implementing RendererProtocol for headless output.

This module provides the CliRenderer class that outputs events to
stdout (assistant text) and stderr (progress/tool events).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from soothe.tools.display_names import get_tool_display_name
from soothe.ux.core.message_processing import format_tool_call_args
from soothe.ux.core.progress_verbosity import ProgressVerbosity, should_show

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

    def __init__(self, *, verbosity: ProgressVerbosity = "normal") -> None:
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

        sys.stderr.write(f"⚙ {display_name}{args_str}\n")
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
        sys.stderr.write(f"{prefix}ERROR: {error}\n")
        sys.stderr.flush()

    def on_progress_event(
        self,
        event_type: str,  # noqa: ARG002
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
        render_progress_event(data)

    def on_plan_created(self, plan: Plan) -> None:
        """Write plan creation to stderr.

        Args:
            plan: Created plan object.
        """
        self._ensure_newline()
        sys.stderr.write(f"[plan] ● Plan: {plan.goal} ({len(plan.steps)} steps)\n")
        sys.stderr.flush()
        self._state.multi_step_active = len(plan.steps) > 1

    def on_plan_step_started(self, step_id: str, description: str) -> None:
        """Write plan step start to stderr.

        Args:
            step_id: Step identifier.
            description: Step description.
        """
        self._ensure_newline()
        sys.stderr.write(f"[plan] ├ Step {step_id}: {description}\n")
        sys.stderr.flush()

    def on_plan_step_completed(
        self,
        step_id: str,
        success: bool,  # noqa: FBT001
        duration_ms: int,
    ) -> None:
        """Write plan step completion to stderr.

        Args:
            step_id: Step identifier.
            success: True if step succeeded.
            duration_ms: Step duration in milliseconds.
        """
        self._ensure_newline()
        icon = "✓" if success else "✗"
        line = f"[plan] ├ Step {step_id} {icon}"
        if duration_ms > 0:
            line += f" ({duration_ms}ms)"
        sys.stderr.write(line + "\n")
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
