"""Unit tests for goal completion hybrid policy (IG-298)."""

from __future__ import annotations

import pytest

from soothe.core.loop.planning.dag import PlanDAG
from soothe.core.loop.planning.manager import (
    CompletionStrategy,
    PlanManager,
    determine_goal_completion_needs,
)
from soothe.core.loop.state.schemas import (
    AgentDecision,
    LoopState,
    PlanResult,
    StepAction,
    StepResult,
)


def mock_loop_state(**kwargs) -> LoopState:
    """Create mock LoopState with default values."""
    defaults = {
        "goal": "test goal",
        "thread_id": "test-thread",
        "iteration": 0,
        "step_results": [],
        "last_execute_wave_parallel_multi_step": False,
        "last_wave_hit_subagent_cap": False,
        "last_execute_assistant_text": "",
        "current_decision": None,
        "loop_messages": [],
    }
    return LoopState(**{**defaults, **kwargs})


# --- determine_goal_completion_needs tests (standalone function) ---


def test_llm_only_mode_true():
    state = mock_loop_state()
    result = determine_goal_completion_needs(llm_decision=True, state=state, mode="llm_only")
    assert result is True


def test_llm_only_mode_false():
    state = mock_loop_state()
    result = determine_goal_completion_needs(llm_decision=False, state=state, mode="llm_only")
    assert result is False


def test_default_mode_is_llm_only():
    state = mock_loop_state(last_execute_wave_parallel_multi_step=True)
    assert determine_goal_completion_needs(llm_decision=False, state=state) is False
    assert determine_goal_completion_needs(llm_decision=True, state=state) is True


def test_heuristic_only_mode_parallel_multi_step():
    state = mock_loop_state(last_execute_wave_parallel_multi_step=True)
    result = determine_goal_completion_needs(llm_decision=False, state=state, mode="heuristic_only")
    assert result is True


def test_hybrid_mode_llm_true_honored():
    state = mock_loop_state()
    result = determine_goal_completion_needs(llm_decision=True, state=state, mode="hybrid")
    assert result is True


def test_hybrid_mode_llm_false_heuristic_true():
    state = mock_loop_state(last_execute_wave_parallel_multi_step=True)
    result = determine_goal_completion_needs(llm_decision=False, state=state, mode="hybrid")
    assert result is True


def test_hybrid_mode_both_false():
    step_results = [
        StepResult(
            step_id="S1",
            success=True,
            outcome={"type": "file_read"},
            duration_ms=100,
            thread_id="t1",
        ),
    ]
    state = mock_loop_state(
        iteration=0, step_results=step_results, last_execute_wave_parallel_multi_step=False
    )
    result = determine_goal_completion_needs(llm_decision=False, state=state, mode="hybrid")
    assert result is False


def test_hybrid_mode_zero_execution_no_heuristic_fallback():
    state = mock_loop_state(
        iteration=0, step_results=[], last_execute_wave_parallel_multi_step=False
    )
    result = determine_goal_completion_needs(llm_decision=False, state=state, mode="hybrid")
    assert result is False


def test_heuristic_parallel_multi_step():
    state = mock_loop_state(last_execute_wave_parallel_multi_step=True)
    pm = PlanManager(goal="test")
    result = pm._heuristic_requires_goal_completion(state)
    assert result is True


def test_heuristic_subagent_cap():
    state = mock_loop_state(last_wave_hit_subagent_cap=True)
    pm = PlanManager(goal="test")
    result = pm._heuristic_requires_goal_completion(state)
    assert result is True


def test_heuristic_single_wave():
    state = mock_loop_state(iteration=1)
    pm = PlanManager(goal="test")
    result = pm._heuristic_requires_goal_completion(state)
    assert result is False


def test_heuristic_few_steps():
    step_results = [
        StepResult(step_id="S1", success=True, outcome={}, duration_ms=100, thread_id="t1"),
    ]
    state = mock_loop_state(step_results=step_results)
    pm = PlanManager(goal="test")
    result = pm._heuristic_requires_goal_completion(state)
    assert result is False


def test_heuristic_dag_dependencies():
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(
                id="S1",
                description="Step 1",
                dependencies=["S0", "S2", "S3"],
            ),
            StepAction(id="S2", description="Step 2", dependencies=[]),
        ],
        execution_mode="dependency",
    )
    state = mock_loop_state(current_decision=decision)
    pm = PlanManager(goal="test")
    result = pm._heuristic_requires_goal_completion(state)
    assert result is True


def test_heuristic_no_dependencies():
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="S1", description="Step 1", dependencies=[]),
            StepAction(id="S2", description="Step 2", dependencies=[]),
        ],
        execution_mode="parallel",
    )
    step_results = [
        StepResult(step_id="S1", success=True, outcome={}, duration_ms=100, thread_id="t1"),
    ]
    state = mock_loop_state(current_decision=decision, step_results=step_results)
    pm = PlanManager(goal="test")
    result = pm._heuristic_requires_goal_completion(state)
    assert result is False


def test_heuristic_failed_steps_low_success_rate():
    pm = PlanManager(goal="test")
    # Ingest a plan with two steps
    d = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="S1", description="Step 1"),
            StepAction(id="S2", description="Step 2"),
        ],
        execution_mode="parallel",
    )
    pr = PlanResult(
        status="continue", goal_progress="low", plan_action="new", decision=d, next_action=""
    )
    pm.ingest_plan(pr, "KFA", 0)
    # Mark outcomes: 1 success, 1 failure → success_rate=0.5 < 0.6 threshold
    pm.record_step_outcomes(
        [
            StepResult(step_id="S1", success=True, outcome={}, duration_ms=100, thread_id="t1"),
            StepResult(
                step_id="S2",
                success=False,
                outcome={},
                error="Error",
                duration_ms=100,
                thread_id="t1",
            ),
        ]
    )

    state = mock_loop_state()
    result = pm._heuristic_requires_goal_completion(state)
    assert result is True


def test_heuristic_failed_steps_high_success_rate():
    step_results = [
        StepResult(step_id="S1", success=True, outcome={}, duration_ms=100, thread_id="t1"),
        StepResult(step_id="S2", success=True, outcome={}, duration_ms=100, thread_id="t1"),
        StepResult(step_id="S3", success=True, outcome={}, duration_ms=100, thread_id="t1"),
        StepResult(
            step_id="S4", success=False, outcome={}, error="Error", duration_ms=100, thread_id="t1"
        ),
    ]
    state = mock_loop_state(step_results=step_results)
    pm = PlanManager(goal="test")
    result = pm._heuristic_requires_goal_completion(state)
    assert result is False


def test_heuristic_combined_complexity():
    state = mock_loop_state(
        iteration=2,
        last_execute_wave_parallel_multi_step=True,
        step_results=[
            StepResult(
                step_id="S1",
                success=True,
                outcome={"type": "file_read"},
                duration_ms=100,
                thread_id="t1",
            ),
            StepResult(
                step_id="S2",
                success=True,
                outcome={"type": "file_read"},
                duration_ms=100,
                thread_id="t1",
            ),
        ],
    )
    pm = PlanManager(goal="test")
    result = pm._heuristic_requires_goal_completion(state)
    assert result is True


def test_heuristic_simple_execution():
    step_results = [
        StepResult(
            step_id="S1",
            success=True,
            outcome={"type": "file_read"},
            duration_ms=100,
            thread_id="t1",
        ),
    ]
    state = mock_loop_state(
        iteration=0,
        step_results=step_results,
        last_execute_wave_parallel_multi_step=False,
        last_wave_hit_subagent_cap=False,
        current_decision=None,
    )
    pm = PlanManager(goal="test")
    result = pm._heuristic_requires_goal_completion(state)
    assert result is False


def test_heuristic_empty_step_results_no_completion_signal():
    state = mock_loop_state(
        iteration=0,
        step_results=[],
        last_execute_wave_parallel_multi_step=False,
        last_wave_hit_subagent_cap=False,
        current_decision=None,
    )
    pm = PlanManager(goal="test")
    result = pm._heuristic_requires_goal_completion(state)
    assert result is False


# --- PlanDAG tests ---


def test_plandag_ingest_plan_new():
    dag = PlanDAG()
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
    dag.ingest_plan(plan_result, "KFA", 0)
    assert dag.total_steps == 2
    assert dag.plan_count == 1
    assert "01" in dag.nodes
    assert "02" in dag.nodes


def test_plandag_mark_completed():
    dag = PlanDAG()
    decision = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="01", description="Step 1")],
        execution_mode="parallel",
    )
    plan_result = PlanResult(
        status="continue", goal_progress="low", plan_action="new", decision=decision, next_action=""
    )
    dag.ingest_plan(plan_result, "KFA", 0)
    outcome = StepResult(step_id="01", success=True, outcome={}, duration_ms=10, thread_id="t")
    dag.mark_completed("01", outcome)
    assert dag.completed_steps == 1
    assert dag.remaining_steps == 0


def test_plandag_mark_failed():
    dag = PlanDAG()
    decision = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="01", description="Step 1")],
        execution_mode="parallel",
    )
    plan_result = PlanResult(
        status="continue", goal_progress="low", plan_action="new", decision=decision, next_action=""
    )
    dag.ingest_plan(plan_result, "KFA", 0)
    outcome = StepResult(
        step_id="01", success=False, outcome={}, error="err", duration_ms=10, thread_id="t"
    )
    dag.mark_failed("01", outcome)
    assert dag.failed_steps == 1
    assert dag.success_rate == 0.0


def test_plandag_dag_dependencies():
    dag = PlanDAG()
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
    dag.ingest_plan(plan_result, "KFA", 0)
    assert dag.has_dag_dependencies is True
    assert dag.max_chain_depth == 3


def test_plandag_multiple_plans():
    dag = PlanDAG()
    # Plan 1
    d1 = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="01", description="Step 1")],
        execution_mode="parallel",
    )
    pr1 = PlanResult(
        status="continue", goal_progress="low", plan_action="new", decision=d1, next_action=""
    )
    dag.ingest_plan(pr1, "KFA", 0)

    # Plan 2 (replan)
    d2 = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="KFA-02", description="New step")],
        execution_mode="parallel",
    )
    pr2 = PlanResult(
        status="continue", goal_progress="medium", plan_action="new", decision=d2, next_action=""
    )
    dag.ingest_plan(pr2, "XYZ", 1)

    assert dag.plan_count == 2
    assert dag.total_steps == 2  # 01 from plan1, KFA-02 from plan2


# --- PlanManager.determine_completion_strategy tests ---


def test_strategy_always_synthesize():
    pm = PlanManager(goal="test")
    pr = PlanResult(status="done", goal_progress="complete", require_goal_completion=False)
    state = mock_loop_state()
    assert (
        pm.determine_completion_strategy(state, pr, "always_synthesize")
        == CompletionStrategy.SYNTHESIZE
    )


def test_strategy_ledger_direct_simple():
    pm = PlanManager(goal="test")
    # Simple: 1 plan, no deps, no failures, <=2 steps
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
    pm.ingest_plan(pr, "KFA", 0)
    outcome = StepResult(step_id="01", success=True, outcome={}, duration_ms=10, thread_id="t")
    pm.record_step_outcomes([outcome])

    state = mock_loop_state()
    assert (
        pm.determine_completion_strategy(state, pr, "adaptive") == CompletionStrategy.LEDGER_DIRECT
    )


def test_strategy_synthesize_multiple_plans():
    pm = PlanManager(goal="test")
    d1 = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="01", description="Step 1")],
        execution_mode="parallel",
    )
    pr1 = PlanResult(
        status="continue", goal_progress="low", plan_action="new", decision=d1, next_action=""
    )
    pm.ingest_plan(pr1, "KFA", 0)

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
    pm.ingest_plan(pr2, "XYZ", 1)

    state = mock_loop_state()
    assert pm.determine_completion_strategy(state, pr2, "adaptive") == CompletionStrategy.SYNTHESIZE


def test_strategy_synthesize_failed_steps():
    pm = PlanManager(goal="test")
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
    pm.ingest_plan(pr, "KFA", 0)
    pm.record_step_outcomes(
        [
            StepResult(step_id="01", success=True, outcome={}, duration_ms=10, thread_id="t"),
            StepResult(
                step_id="02", success=False, outcome={}, error="err", duration_ms=10, thread_id="t"
            ),
        ]
    )

    state = mock_loop_state()
    assert pm.determine_completion_strategy(state, pr, "adaptive") == CompletionStrategy.SYNTHESIZE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
