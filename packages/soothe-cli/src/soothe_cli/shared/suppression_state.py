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
    is accumulated for the goal completion output.

    Usage:
        # In renderer state:
        suppression: SuppressionState = field(default_factory=SuppressionState)

        # Check suppression (assistant stdout only in CliRenderer):
        if suppression.should_suppress_output():
            return

        # Track from events:
        suppression.track_from_event(event_type, data)

        # Get goal completion:
        if suppression.should_emit_goal_completion(event_type):
            text = suppression.get_final_response()
            # ... emit text ...
    """

    # Multi-step plan suppression flag
    multi_step_active: bool = False

    # Agentic loop (max_iterations>1): keep suppressing until loop.completed
    # even if status idle/on_turn_end cleared multi_step_active first
    agentic_stdout_suppressed: bool = False

    # Track if final stdout already emitted (prevent duplicate emission)
    agentic_final_stdout_emitted: bool = False

    # Accumulated response text for the goal completion output
    full_response: list[str] = field(default_factory=list)

    # Execute-phase tracking (namespace-aware)
    # True during agent_loop.step execution (tool calls, file ops)
    # Suppresses AIMessage prose in quiet/normal verbosity
    execute_phase_active_by_namespace: dict[tuple, bool] = field(default_factory=dict)

    # Per-namespace response accumulators (for execute-phase text buffering)
    full_response_by_namespace: dict[tuple, list[str]] = field(default_factory=dict)

    def should_suppress_output(self, namespace: tuple = ()) -> bool:
        """Check if output should be suppressed.

        Args:
            namespace: Namespace tuple for agent context (default: () for main agent).

        Returns:
            True if multi-step, agentic loop, or execute-phase is active.
        """
        execute_phase = self.execute_phase_active_by_namespace.get(namespace, False)
        return (
            self.multi_step_active
            or (self.agentic_stdout_suppressed and not self.agentic_final_stdout_emitted)
            or execute_phase
        )

    def should_emit_goal_completion(
        self,
        event_type: str,
    ) -> bool:
        """Check if goal completion should be emitted on loop completion.

        Args:
            event_type: Event type string.
        Returns:
            True if goal completion should be emitted.
        """
        if event_type != "soothe.cognition.agent_loop.completed":
            return False

        if self.agentic_final_stdout_emitted:
            return False

        # Mark flag when emitting
        should_emit = self.multi_step_active or self.agentic_stdout_suppressed
        if should_emit:
            self.agentic_final_stdout_emitted = True

        return should_emit

    def track_from_event(self, event_type: str, data: dict) -> None:
        """Track suppression state from progress event.

        Args:
            event_type: Event type string.
            data: Event payload dict.

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

        # Note: agentic_final_stdout_emitted flag is set in should_emit_goal_completion()
        # after checking the condition, not here (order matters for rendering logic)

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

    def track_execute_phase_from_event(self, event_type: str, namespace: tuple = ()) -> None:
        """Track execute-phase state from agent_loop.step events.

        Execute-phase suppresses AIMessage prose during tool execution steps,
        allowing only synthesis/reasoning text to display.

        Args:
            event_type: Event type string.
            namespace: Namespace tuple for agent context.
        """
        if event_type == "soothe.cognition.agent_loop.step.started":
            self.execute_phase_active_by_namespace[namespace] = True
            # Initialize response accumulator for namespace if needed
            if namespace not in self.full_response_by_namespace:
                self.full_response_by_namespace[namespace] = []
        elif event_type in (
            "soothe.cognition.agent_loop.step.completed",
            "soothe.cognition.agent_loop.completed",
        ):
            self.execute_phase_active_by_namespace[namespace] = False

    def get_final_response(self, namespace: tuple = ()) -> str:
        """Get accumulated final response text.

        Args:
            namespace: Namespace tuple for agent context.

        Returns:
            Aggregated response text.
        """
        # Use namespace-specific accumulator if tracking
        accumulator = self.full_response_by_namespace.get(namespace, self.full_response)

        return "".join(accumulator)

    def accumulate_text(self, text: str, namespace: tuple = ()) -> None:
        """Accumulate text for final response.

        Args:
            text: Text chunk to accumulate.
            namespace: Namespace tuple for agent context.
        """
        # Use namespace-specific accumulator if tracking, else global
        if namespace in self.full_response_by_namespace:
            self.full_response_by_namespace[namespace].append(text)
        else:
            self.full_response.append(text)

    def reset_turn(self) -> None:
        """Reset state for next turn.

        Called on turn end (status becomes idle/stopped).
        Clears suppression flags and accumulated response.
        """
        self.multi_step_active = False
        self.full_response.clear()
        # Clear execute-phase state
        self.execute_phase_active_by_namespace.clear()
        self.full_response_by_namespace.clear()

    def reset_session(self) -> None:
        """Reset all session state.

        Called when thread changes.
        """
        self.multi_step_active = False
        self.agentic_stdout_suppressed = False
        self.agentic_final_stdout_emitted = False
        self.full_response.clear()
        # Clear execute-phase state
        self.execute_phase_active_by_namespace.clear()
        self.full_response_by_namespace.clear()
