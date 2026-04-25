"""Shared suppression state for multi-step/agentic loop execution (IG-143).

This module provides reusable state tracking and logic for suppressing
intermediate output during multi-step plan execution and agentic loops.
Both CLI and TUI renderers use this to prevent redundant intermediate output.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from soothe_sdk.core.events import DEFAULT_AGENT_LOOP_MAX_ITERATIONS


@dataclass
class SuppressionState:
    """Shared state for IG-143 multi-step/agentic suppression.

    This tracks execution state to suppress intermediate LLM responses on stdout
    during multi-step execution. Tool calls and tool results on stderr are still
    rendered by ``CliRenderer`` at normal+ verbosity; only assistant streaming text
    is accumulated for the final report.

    Usage:
        # In renderer state:
        suppression: SuppressionState = field(default_factory=SuppressionState)

        # Check suppression (assistant stdout only in CliRenderer):
        if suppression.should_suppress_output():
            return

        # Track from events:
        suppression.track_from_event(event_type, data)

        # Get final report:
        if suppression.should_emit_final_report(event_type, final_stdout):
            text = suppression.get_final_response(final_stdout)
            # ... emit text ...
    """

    # Multi-step plan suppression flag
    multi_step_active: bool = False

    # Agentic loop (max_iterations>1): keep suppressing until loop.completed
    # even if status idle/on_turn_end cleared multi_step_active first
    agentic_stdout_suppressed: bool = False

    # Track if final stdout already emitted (prevent duplicate emission)
    agentic_final_stdout_emitted: bool = False

    # Accumulated response text for final report
    full_response: list[str] = field(default_factory=list)

    def should_suppress_output(self) -> bool:
        """Check if output should be suppressed.

        Returns:
            True if multi-step or agentic loop is active and suppressing.
        """
        return self.multi_step_active or (
            self.agentic_stdout_suppressed and not self.agentic_final_stdout_emitted
        )

    def should_emit_final_report(
        self,
        event_type: str,
        final_stdout: str,
    ) -> bool:
        """Check if final report should be emitted on loop completion.

        Args:
            event_type: Event type string.
            final_stdout: Final stdout message from event data.

        Returns:
            True if final report should be emitted.
        """
        if event_type != "soothe.cognition.agent_loop.completed":
            return False

        if not final_stdout:
            return False

        if self.agentic_final_stdout_emitted:
            return False

        # Mark flag when emitting
        should_emit = self.multi_step_active or self.agentic_stdout_suppressed
        if should_emit:
            self.agentic_final_stdout_emitted = True

        return should_emit

    def track_from_event(self, event_type: str, data: dict) -> str:
        """Track suppression state from progress event.

        Args:
            event_type: Event type string.
            data: Event payload dict.

        Returns:
            Final stdout message if present (for emission after tracking).
        """
        # Track suppression state from agentic loop start.
        # Suppress intermediate output only when max_iterations > 1 (multi-step mode).
        # In single-step mode (max_iterations == 1), stdout flows normally and final_stdout
        # should NOT be emitted separately to avoid duplication (IG-143 follow-up).
        if event_type == "soothe.cognition.agent_loop.started":
            max_iterations = data.get("max_iterations", DEFAULT_AGENT_LOOP_MAX_ITERATIONS)
            if max_iterations > 1:
                self.multi_step_active = True
                self.agentic_stdout_suppressed = True
                self.agentic_final_stdout_emitted = False

        # Backup suppression: suppress after iteration 1+ if loop.started was filtered
        if event_type == "soothe.cognition.agent_loop.reasoning":
            try:
                iteration = int(data.get("iteration", 0))
            except (TypeError, ValueError):
                iteration = 0
            if iteration >= 1 and not self.agentic_final_stdout_emitted:
                self.agentic_stdout_suppressed = True

        # Extract final stdout message from loop completion
        payload = dict(data)
        final_stdout = (payload.pop("final_stdout_message", None) or "").strip()

        # Note: agentic_final_stdout_emitted flag is set in should_emit_final_report()
        # after checking the condition, not here (order matters for rendering logic)

        return final_stdout

    def track_from_plan(self, num_steps: int) -> None:
        """Track suppression state from plan creation.

        Args:
            num_steps: Number of steps in the plan.
        """
        self.multi_step_active = num_steps > 1
        # max_iterations==1 does not arm agentic_stdout_suppressed in loop.started;
        # multi-step plans still clear multi_step_active on on_turn_end before
        # loop.completed (test-case1).
        if num_steps > 1:
            self.agentic_stdout_suppressed = True
            self.agentic_final_stdout_emitted = False

    def get_final_response(self, final_stdout: str | None = None) -> str:
        """Get accumulated final response text.

        Args:
            final_stdout: Optional final stdout message to append.

        Returns:
            Aggregated response text.
        """
        if final_stdout:
            stripped = final_stdout.strip()
            if stripped:
                self.full_response.append(stripped)

        # Join accumulated response
        return "".join(self.full_response)

    def accumulate_text(self, text: str) -> None:
        """Accumulate text for final response.

        Args:
            text: Text chunk to accumulate.
        """
        self.full_response.append(text)

    def reset_turn(self) -> None:
        """Reset state for next turn.

        Called on turn end (status becomes idle/stopped).
        Clears suppression flags and accumulated response.
        """
        self.multi_step_active = False
        self.full_response = []

    def reset_session(self) -> None:
        """Reset all session state.

        Called when thread changes.
        """
        self.multi_step_active = False
        self.agentic_stdout_suppressed = False
        self.agentic_final_stdout_emitted = False
        self.full_response = []
