"""Unit tests for goal completion hybrid policy."""

from __future__ import annotations

import pytest

from soothe.context import StepPlanManagerAdapter
from soothe.context.engine import ContextEngine
from soothe.context.models import GoalNode
from soothe.context.planning_models import CompletionStrategy
from soothe.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    PlanResult,
    StepAction,
    StepExecutionRecord,
)
from soothe.sloop.utils.messages import LoopAIMessage


def mock_loop_state(**kwargs) -> LoopState:
    """Create mock LoopState with default values."""
    defaults = {
        "goal": "test goal",
        "thread_id": "test-thread",
        "iteration": 0,
        "step_results": [],
        "last_execute_wave_parallel_multi_step": False,
        "last_wave_hit_subagent_cap": False,
        "current_decision": None,
        "loop_messages": [],
    }
    return LoopState(**{**defaults, **kwargs})


def _make_adapter(goal_description: str = "test") -> StepPlanManagerAdapter:
    ce = ContextEngine()
    goal = GoalNode(description=goal_description)
    ce._dag.add_goal(goal)
    return StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)


# --- StepPlanningSubengine ingest tests (replaces PlanDAG) ---


def test_step_dag_ingest_plan_new() -> None:
    adapter = _make_adapter()
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="01", description="Step 1"),
            StepAction(id="02", description="Step 2"),
        ],
        execution_mode="parallel",
    )
    plan_result = PlanResult(
        status="continue",
        goal_progress="low",
        plan_action="new",
        decision=decision,
        next_action="Do steps",
    )
    adapter.ingest_plan(plan_result, "KFA", 0)
    ctx = adapter.get_planning_context()
    assert ctx.total_steps == 2
    assert "01" in ctx.pending_step_ids
    assert "02" in ctx.pending_step_ids


def test_step_dag_mark_completed() -> None:
    adapter = _make_adapter()
    decision = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="01", description="Step 1")],
        execution_mode="parallel",
    )
    plan_result = PlanResult(
        status="continue", goal_progress="low", plan_action="new", decision=decision, next_action=""
    )
    adapter.ingest_plan(plan_result, "KFA", 0)
    adapter.record_step_outcomes(
        [StepExecutionRecord(step_id="01", success=True, outcome={}, duration_ms=10, thread_id="t")]
    )
    ctx = adapter.get_planning_context()
    assert ctx.completed_steps == 1
    assert ctx.pending_step_ids == set()


def test_step_dag_mark_failed() -> None:
    adapter = _make_adapter()
    decision = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="01", description="Step 1")],
        execution_mode="parallel",
    )
    plan_result = PlanResult(
        status="continue", goal_progress="low", plan_action="new", decision=decision, next_action=""
    )
    adapter.ingest_plan(plan_result, "KFA", 0)
    adapter.record_step_outcomes(
        [
            StepExecutionRecord(
                step_id="01",
                success=False,
                outcome={},
                error="err",
                duration_ms=10,
                thread_id="t",
            )
        ]
    )
    ctx = adapter.get_planning_context()
    assert "01" in ctx.failed_step_ids
    assert ctx.success_rate == 0.0


def test_step_dag_dependencies() -> None:
    adapter = _make_adapter()
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="01", description="Step 1"),
            StepAction(id="02", description="Step 2", dependencies=["01"]),
            StepAction(id="03", description="Step 3", dependencies=["02"]),
        ],
        execution_mode="dependency",
    )
    plan_result = PlanResult(
        status="continue", goal_progress="low", plan_action="new", decision=decision, next_action=""
    )
    adapter.ingest_plan(plan_result, "KFA", 0)
    ctx = adapter.get_planning_context()
    assert ctx.chain_depth == 3


def test_step_dag_multiple_plans() -> None:
    adapter = _make_adapter()
    d1 = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="01", description="Step 1")],
        execution_mode="parallel",
    )
    pr1 = PlanResult(
        status="continue", goal_progress="low", plan_action="new", decision=d1, next_action=""
    )
    adapter.ingest_plan(pr1, "KFA", 0)

    d2 = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="KFA-02", description="New step")],
        execution_mode="parallel",
    )
    pr2 = PlanResult(
        status="continue", goal_progress="medium", plan_action="new", decision=d2, next_action=""
    )
    adapter.ingest_plan(pr2, "XYZ", 1)

    ctx = adapter.get_planning_context()
    assert ctx.total_steps == 2
    assert ctx.replan_count == 1


# --- determine_completion_strategy tests ---


def test_strategy_always_synthesize() -> None:
    adapter = _make_adapter()
    pr = PlanResult(status="done", goal_progress="complete", require_goal_completion=False)
    state = mock_loop_state()
    assert (
        adapter.determine_completion_strategy(state, pr, "always_synthesize")
        == CompletionStrategy.SYNTHESIZE
    )


def test_strategy_ledger_direct_simple() -> None:
    adapter = _make_adapter()
    d = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="01", description="Step 1")],
        execution_mode="parallel",
    )
    pr = PlanResult(
        status="done",
        goal_progress="complete",
        plan_action="new",
        decision=d,
        require_goal_completion=False,
        next_action="",
    )
    adapter.ingest_plan(pr, "KFA", 0)
    adapter.record_step_outcomes(
        [StepExecutionRecord(step_id="01", success=True, outcome={}, duration_ms=10, thread_id="t")]
    )
    state = mock_loop_state(
        loop_messages=[
            LoopAIMessage(
                content="The answer is 42.",
                thread_id="t",
                phase="execute_step",
            )
        ]
    )
    assert (
        adapter.determine_completion_strategy(state, pr, "auto") == CompletionStrategy.LEDGER_DIRECT
    )


def test_strategy_simple_empty_ledger_synthesizes() -> None:
    adapter = _make_adapter()
    d = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="01", description="Step 1")],
        execution_mode="parallel",
    )
    pr = PlanResult(
        status="done",
        goal_progress="complete",
        plan_action="new",
        decision=d,
        require_goal_completion=False,
        next_action="",
    )
    adapter.ingest_plan(pr, "KFA", 0)
    adapter.record_step_outcomes(
        [StepExecutionRecord(step_id="01", success=True, outcome={}, duration_ms=10, thread_id="t")]
    )
    state = mock_loop_state(loop_messages=[])
    assert adapter.determine_completion_strategy(state, pr, "auto") == CompletionStrategy.SYNTHESIZE


def test_strategy_synthesize_multiple_plans() -> None:
    adapter = _make_adapter()
    d1 = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="01", description="Step 1")],
        execution_mode="parallel",
    )
    pr1 = PlanResult(
        status="continue", goal_progress="low", plan_action="new", decision=d1, next_action=""
    )
    adapter.ingest_plan(pr1, "KFA", 0)

    d2 = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="02", description="Step 2")],
        execution_mode="parallel",
    )
    pr2 = PlanResult(
        status="done",
        goal_progress="complete",
        plan_action="new",
        decision=d2,
        require_goal_completion=True,
        next_action="",
    )
    adapter.ingest_plan(pr2, "XYZ", 1)

    state = mock_loop_state()
    assert (
        adapter.determine_completion_strategy(state, pr2, "auto") == CompletionStrategy.SYNTHESIZE
    )


def test_strategy_synthesize_failed_steps() -> None:
    adapter = _make_adapter()
    d = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="01", description="Step 1"),
            StepAction(id="02", description="Step 2"),
        ],
        execution_mode="parallel",
    )
    pr = PlanResult(
        status="done",
        goal_progress="complete",
        plan_action="new",
        decision=d,
        require_goal_completion=True,
        next_action="",
    )
    adapter.ingest_plan(pr, "KFA", 0)
    adapter.record_step_outcomes(
        [
            StepExecutionRecord(
                step_id="01", success=True, outcome={}, duration_ms=10, thread_id="t"
            ),
            StepExecutionRecord(
                step_id="02", success=False, outcome={}, error="err", duration_ms=10, thread_id="t"
            ),
        ]
    )
    state = mock_loop_state()
    assert adapter.determine_completion_strategy(state, pr, "auto") == CompletionStrategy.SYNTHESIZE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
