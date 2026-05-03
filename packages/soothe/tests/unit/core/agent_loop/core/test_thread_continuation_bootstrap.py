"""Tests for IG-325 thread continuation plan bootstrap."""

from datetime import UTC, datetime

from soothe.core.agent_loop.core.thread_continuation_bootstrap import (
    build_thread_continuation_bootstrap_plan,
    thread_continuation_plan_bootstrap_allowed,
)
from soothe.core.agent_loop.state.checkpoint import GoalExecutionRecord
from soothe.core.agent_loop.state.schemas import LoopState, StepResult
from soothe.core.agent_loop.utils.messages import LoopHumanMessage


def _goal_record(
    *,
    iteration: int = 0,
    ledger_entries: int = 0,
) -> GoalExecutionRecord:
    """Build a goal record; non-empty ``loop_messages`` blocks continuation bootstrap on recovery."""
    msgs: list[LoopHumanMessage] = []
    for i in range(ledger_entries):
        msgs.append(
            LoopHumanMessage(
                content=f"ledger turn {i}",
                thread_id="tid",
                iteration=0,
                phase="execute_step",
            )
        )
    return GoalExecutionRecord(
        goal_id="g1",
        goal_text="t",
        thread_id="tid",
        iteration=iteration,
        loop_messages=msgs,
        started_at=datetime.now(UTC),
    )


def test_bootstrap_allowed_fresh_thread_continuation() -> None:
    state = LoopState(goal="follow up", thread_id="t1", iteration=0, step_results=[])
    assert thread_continuation_plan_bootstrap_allowed(
        thread_continuation_mode=True,
        state=state,
        recovery_valid_resume=False,
        goal_record=_goal_record(),
    )


def test_bootstrap_disallowed_without_thread_continuation() -> None:
    state = LoopState(goal="x", thread_id="t1", iteration=0, step_results=[])
    assert not thread_continuation_plan_bootstrap_allowed(
        thread_continuation_mode=False,
        state=state,
        recovery_valid_resume=False,
        goal_record=_goal_record(),
    )


def test_bootstrap_disallowed_when_iteration_nonzero() -> None:
    state = LoopState(goal="x", thread_id="t1", iteration=1, step_results=[])
    assert not thread_continuation_plan_bootstrap_allowed(
        thread_continuation_mode=True,
        state=state,
        recovery_valid_resume=False,
        goal_record=_goal_record(),
    )


def test_bootstrap_disallowed_when_step_results_present() -> None:
    sr = StepResult(
        step_id="s1",
        success=True,
        outcome={"type": "text"},
        duration_ms=1,
        thread_id="t1",
    )
    state = LoopState(goal="x", thread_id="t1", iteration=0, step_results=[sr])
    assert not thread_continuation_plan_bootstrap_allowed(
        thread_continuation_mode=True,
        state=state,
        recovery_valid_resume=False,
        goal_record=_goal_record(),
    )


def test_bootstrap_disallowed_recovery_with_reason_history() -> None:
    state = LoopState(goal="x", thread_id="t1", iteration=0, step_results=[])
    assert not thread_continuation_plan_bootstrap_allowed(
        thread_continuation_mode=True,
        state=state,
        recovery_valid_resume=True,
        goal_record=_goal_record(ledger_entries=1),
    )


def test_bootstrap_disallowed_recovery_with_act_history() -> None:
    state = LoopState(goal="x", thread_id="t1", iteration=0, step_results=[])
    assert not thread_continuation_plan_bootstrap_allowed(
        thread_continuation_mode=True,
        state=state,
        recovery_valid_resume=True,
        goal_record=_goal_record(ledger_entries=1),
    )


def test_bootstrap_disallowed_recovery_iteration_advances() -> None:
    state = LoopState(goal="x", thread_id="t1", iteration=0, step_results=[])
    assert not thread_continuation_plan_bootstrap_allowed(
        thread_continuation_mode=True,
        state=state,
        recovery_valid_resume=True,
        goal_record=_goal_record(iteration=1),
    )


def test_bootstrap_disallowed_recovery_goal_record_none() -> None:
    state = LoopState(goal="x", thread_id="t1", iteration=0, step_results=[])
    assert not thread_continuation_plan_bootstrap_allowed(
        thread_continuation_mode=True,
        state=state,
        recovery_valid_resume=True,
        goal_record=None,
    )


def test_bootstrap_allowed_recovery_iteration_zero_clean_record() -> None:
    state = LoopState(goal="x", thread_id="t1", iteration=0, step_results=[])
    assert thread_continuation_plan_bootstrap_allowed(
        thread_continuation_mode=True,
        state=state,
        recovery_valid_resume=True,
        goal_record=_goal_record(iteration=0, ledger_entries=0),
    )


def test_build_bootstrap_plan_shape() -> None:
    pr = build_thread_continuation_bootstrap_plan("user follow-up")
    assert pr.status == "continue"
    assert pr.plan_action == "new"
    assert pr.decision is not None
    assert pr.decision.type == "execute_steps"
    assert len(pr.decision.steps) == 1
    assert pr.decision.execution_mode == "sequential"
