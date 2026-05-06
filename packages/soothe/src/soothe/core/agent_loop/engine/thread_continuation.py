"""Thread continuation first-plan bootstrap (IG-325).

When intent classification is ``thread_continuation`` and loop state is a true
first plan for this run, skip the initial planner LLM and inject a single-step
``PlanResult``. Guards use execution/checkpoint structure only (no query heuristics).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from soothe.core.agent_loop.state.schemas import (
    AgentDecision,
    LoopState,
    PlanResult,
    StepAction,
)

if TYPE_CHECKING:
    from soothe.core.agent_loop.state.checkpoint import GoalExecutionRecord


def thread_continuation_plan_bootstrap_allowed(
    *,
    thread_continuation_mode: bool,
    state: LoopState,
    recovery_valid_resume: bool,
    goal_record: GoalExecutionRecord | None,
) -> bool:
    """Return True when the first Plan call may use a synthetic bootstrap result.

    Args:
        thread_continuation_mode: True when intent is ``thread_continuation``.
        state: Current loop state (iteration, step_results).
        recovery_valid_resume: True when resuming a running checkpoint with a valid
            ``GoalExecutionRecord`` (not the invalid-index re-init path).
        goal_record: Active goal record when in recovery, else the new goal record
            from ``start_new_goal`` on a fresh run.

    Returns:
        Whether bootstrap is structurally allowed.
    """
    if not thread_continuation_mode:
        return False
    if state.iteration != 0:
        return False
    if state.step_results:
        return False

    if recovery_valid_resume:
        if goal_record is None:
            return False
        if goal_record.iteration != 0:
            return False
        if goal_record.loop_messages:
            return False

    return True


def build_thread_continuation_bootstrap_plan(_goal: str) -> PlanResult:
    """Build a synthetic first ``PlanResult`` for thread continuation (IG-325, RFC-214).

    The loop goal is the user's current request on ``LoopState.goal``; prior turns
    are supplied via ``loop_messages`` ledger for Execute prompts (RFC-214).

    Args:
        _goal: Loop goal text (reserved for callers; body uses ``LoopState``).

    Returns:
        ``PlanResult`` with ``status=continue`` and a single sequential step.
    """
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(
                description=(
                    "Using the prior Human/Assistant turns in the AgentLoop ledger "
                    "(loop_messages) and the loop goal as the user's current "
                    "request, respond and complete the follow-up. Use tools only when needed."
                ),
                expected_output=(
                    "Output that satisfies the user's request in light of the ledger history "
                    "and the stated goal."
                ),
            )
        ],
        execution_mode="sequential",
        reasoning="IG-325: Thread continuation first-plan bootstrap (no planner LLM).",
    )
    return PlanResult(
        status="continue",
        goal_progress="low",  # IG-399: descriptive level (initial bootstrap)
        assessment_reasoning="IG-325 thread continuation: initial planner call skipped.",
        plan_reasoning="Single execute wave from thread context and loop goal.",
        next_action="Execute one focused step for the user's follow-up request.",
        plan_action="new",
        decision=decision,
        require_goal_completion=False,
    )
