"""Events for LoopAgent (soothe.cognition.loop.*).

Implements the event system for Layer 2 execution with the cognition namespace.

Event taxonomy:
- Lifecycle events: loop started/completed
- Iteration events: iteration started/completed
- Phase events: plan/act/judge phases
- Decision events: judgment decisions
- Error events: failure modes
"""

from __future__ import annotations

from typing import Any

from soothe.core.base_events import SootheEvent

# Lifecycle Events


class LoopStartedEvent(SootheEvent):
    """Loop execution started."""

    type: str = "soothe.cognition.loop.started"
    goal: str
    planning_strategy: str


class LoopCompletedEvent(SootheEvent):
    """Loop execution completed."""

    type: str = "soothe.cognition.loop.completed"
    iterations: int
    final_status: str  # "done", "max_iterations", "error"


# Iteration Events


class IterationStartedEvent(SootheEvent):
    """Iteration started."""

    type: str = "soothe.cognition.loop.iteration.started"
    iteration: int


class IterationCompletedEvent(SootheEvent):
    """Iteration completed."""

    type: str = "soothe.cognition.loop.iteration.completed"
    iteration: int
    duration_ms: int


# Phase Events


class PlanPhaseStartedEvent(SootheEvent):
    """PLAN phase started."""

    type: str = "soothe.cognition.loop.phase.plan.started"
    iteration: int


class PlanPhaseCompletedEvent(SootheEvent):
    """PLAN phase completed."""

    type: str = "soothe.cognition.loop.phase.plan.completed"
    iteration: int
    decision: dict[str, Any]  # AgentDecision


class ActPhaseStartedEvent(SootheEvent):
    """ACT phase started."""

    type: str = "soothe.cognition.loop.phase.act.started"
    iteration: int
    tool_name: str


class ActPhaseCompletedEvent(SootheEvent):
    """ACT phase completed."""

    type: str = "soothe.cognition.loop.phase.act.completed"
    iteration: int
    result: dict[str, Any]  # ToolOutput


class JudgePhaseStartedEvent(SootheEvent):
    """JUDGE phase started."""

    type: str = "soothe.cognition.loop.phase.judge.started"
    iteration: int


class JudgePhaseCompletedEvent(SootheEvent):
    """JUDGE phase completed."""

    type: str = "soothe.cognition.loop.phase.judge.completed"
    iteration: int
    judgment: dict[str, Any]  # JudgeResult


# Decision Events


class JudgmentDecisionEvent(SootheEvent):
    """Judgment decision made."""

    type: str = "soothe.cognition.loop.judgment.decision"
    status: str
    reason: str


class RetryTriggeredEvent(SootheEvent):
    """Retry triggered."""

    type: str = "soothe.cognition.loop.retry.triggered"
    iteration: int
    tool_name: str
    next_hint: str | None


class ReplanTriggeredEvent(SootheEvent):
    """Replan triggered."""

    type: str = "soothe.cognition.loop.replan.triggered"
    iteration: int
    reason: str


# Error Events


class LoopErrorEvent(SootheEvent):
    """Loop error occurred."""

    type: str = "soothe.cognition.loop.error"
    iteration: int
    error_type: str
    error_message: str


class MaxIterationsReachedEvent(SootheEvent):
    """Max iterations reached."""

    type: str = "soothe.cognition.loop.error.max_iterations"
    max_iterations: int


class DegenerateRetryDetectedEvent(SootheEvent):
    """Degenerate retry detected."""

    type: str = "soothe.cognition.loop.error.degenerate_retry"
    tool_name: str
    tool_args: dict[str, Any]
    repetition_count: int


# ---------------------------------------------------------------------------
# Self-registration (called at module import time)
# ---------------------------------------------------------------------------
def _register_events() -> None:
    """Register all LoopAgent events with the global registry."""
    from soothe.core.event_catalog import register_event

    # Lifecycle events
    register_event(
        LoopStartedEvent,
        summary_template="Loop started: {goal[:50]} (strategy={planning_strategy})",
    )
    register_event(
        LoopCompletedEvent,
        summary_template="Loop completed: {iterations} iterations, {final_status}",
    )

    # Iteration events
    register_event(
        IterationStartedEvent,
        summary_template="Iteration {iteration} started",
    )
    register_event(
        IterationCompletedEvent,
        summary_template="Iteration {iteration}: {duration_ms}ms",
    )

    # Phase events
    register_event(
        PlanPhaseStartedEvent,
        verbosity="debug",
        summary_template="PLAN phase started (iteration {iteration})",
    )
    register_event(
        PlanPhaseCompletedEvent,
        summary_template="PLAN phase completed",
    )
    register_event(
        ActPhaseStartedEvent,
        verbosity="debug",
        summary_template="ACT phase: {tool_name}",
    )
    register_event(
        ActPhaseCompletedEvent,
        summary_template="ACT phase completed",
    )
    register_event(
        JudgePhaseStartedEvent,
        verbosity="debug",
        summary_template="JUDGE phase started (iteration {iteration})",
    )
    register_event(
        JudgePhaseCompletedEvent,
        summary_template="JUDGE phase completed",
    )

    # Decision events
    register_event(
        JudgmentDecisionEvent,
        summary_template="Judgment: {status} - {reason[:80]}",
    )
    register_event(
        RetryTriggeredEvent,
        summary_template="Retry triggered: {tool_name} (hint={next_hint})",
    )
    register_event(
        ReplanTriggeredEvent,
        summary_template="Replan triggered: {reason[:80]}",
    )

    # Error events
    register_event(
        LoopErrorEvent,
        verbosity="error",
        summary_template="Loop error: {error_type} - {error_message}",
    )
    register_event(
        MaxIterationsReachedEvent,
        verbosity="error",
        summary_template="Max iterations reached: {max_iterations}",
    )
    register_event(
        DegenerateRetryDetectedEvent,
        verbosity="error",
        summary_template="Degenerate retry: {tool_name} (x{repetition_count})",
    )


# Auto-register at module import
_register_events()
