"""Tests for Context Engine planning submodule (RFC-624 Phase 3c).

Covers: completion.py heuristics, StepPlanningSubengine, StepPlanManagerAdapter,
GoalScheduler, GoalPlanningSubengine, PlanningFacade.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.models import GoalNode, StepNode
from soothe.foundation.context.planning import (
    GoalPlanningSubengine,
    GoalScheduler,
    PlanningFacade,
    StepPlanManagerAdapter,
    StepPlanningSubengine,
)
from soothe.foundation.context.planning.completion import (
    DAG_DEPENDENCY_THRESHOLD,
    LOW_SUCCESS_RATE_THRESHOLD,
    SIMPLE_DAG_LEDGER_DIRECT_MAX_STEPS,
    STRUCTURED_PAYLOAD_MIN_LINES,
    can_return_directly_from_ledger,
    dag_requires_synthesis,
    determine_completion_strategy,
    determine_goal_completion_needs,
    heuristic_requires_goal_completion,
    is_rich_enough,
    is_simple_execution,
    overlaps_with_plan_output,
)
from soothe.foundation.context.planning.models import (
    DagPlanningContext,
    DecompositionRequest,
    DecompositionResult,
    OrchestrationStrategy,
    PlanWave,
    SubGoalSpec,
)
from soothe.foundation.loop.state.schemas import (
    AgentDecision,
    PlanResult,
    StepAction,
    StepResult,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _make_step_action(step_id: str, desc: str, deps: list[str] | None = None) -> StepAction:
    return StepAction(id=step_id, description=desc, dependencies=deps or [])


def _make_plan_result(
    steps: list[StepAction] | None = None,
    status: str = "continue",
    plan_action: str = "new",
    require_goal_completion: bool = True,
    full_output: str = "",
) -> PlanResult:
    decision = None
    if plan_action == "new":
        if steps:
            decision = AgentDecision(type="execute_steps", steps=steps)
        else:
            decision = AgentDecision(
                type="execute_steps",
                steps=[StepAction(id="01", description="Dummy")],
            )
    return PlanResult(
        status=status,
        plan_action=plan_action,
        decision=decision,
        evidence_summary="",
        goal_progress="none",
        next_action="test",
        require_goal_completion=require_goal_completion,
        full_output=full_output,
    )


def _make_step_result(step_id: str, success: bool = True) -> StepResult:
    return StepResult(
        step_id=step_id,
        success=success,
        duration_ms=100,
        thread_id="test-thread",
        error="test error" if not success else None,
    )


def _make_mock_state(**overrides: Any) -> MagicMock:
    state = MagicMock()
    state.iteration = 0
    state.goal = "Test goal"
    state.thread_id = "test-thread"
    state.workspace = None
    state.current_decision = None
    state.loop_messages = []
    state.last_execute_wave_parallel_multi_step = False
    state.last_wave_hit_subagent_cap = False
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


# ═══════════════════════════════════════════════════════════════════════
# completion.py — heuristic functions
# ═══════════════════════════════════════════════════════════════════════


class TestHeuristicRequiresGoalCompletion:
    def test_parallel_multi_step_triggers(self) -> None:
        assert (
            heuristic_requires_goal_completion(
                dag_failed_steps=0,
                dag_completed_steps=2,
                last_execute_wave_parallel_multi_step=True,
                last_wave_hit_subagent_cap=False,
            )
            is True
        )

    def test_subagent_cap_triggers(self) -> None:
        assert (
            heuristic_requires_goal_completion(
                dag_failed_steps=0,
                dag_completed_steps=2,
                last_execute_wave_parallel_multi_step=False,
                last_wave_hit_subagent_cap=True,
            )
            is True
        )

    def test_low_success_rate_triggers(self) -> None:
        assert (
            heuristic_requires_goal_completion(
                dag_failed_steps=3,
                dag_completed_steps=1,
                last_execute_wave_parallel_multi_step=False,
                last_wave_hit_subagent_cap=False,
            )
            is True
        )

    def test_high_success_rate_with_failures_no_trigger(self) -> None:
        assert (
            heuristic_requires_goal_completion(
                dag_failed_steps=1,
                dag_completed_steps=9,
                last_execute_wave_parallel_multi_step=False,
                last_wave_hit_subagent_cap=False,
            )
            is False
        )

    def test_dag_dependency_threshold_triggers(self) -> None:
        step = _make_step_action("01", "S", deps=["a", "b", "c"])
        assert (
            heuristic_requires_goal_completion(
                dag_failed_steps=0,
                dag_completed_steps=1,
                last_execute_wave_parallel_multi_step=False,
                last_wave_hit_subagent_cap=False,
                current_decision_steps=[step],
            )
            is True
        )

    def test_simple_execution_no_trigger(self) -> None:
        assert (
            heuristic_requires_goal_completion(
                dag_failed_steps=0,
                dag_completed_steps=1,
                last_execute_wave_parallel_multi_step=False,
                last_wave_hit_subagent_cap=False,
            )
            is False
        )


class TestIsSimpleExecution:
    def test_single_wave_no_deps_no_failures(self) -> None:
        assert (
            is_simple_execution(
                plan_wave_count=1,
                has_dag_dependencies=False,
                failed_steps=0,
                total_steps=2,
            )
            is True
        )

    def test_replan_not_simple(self) -> None:
        assert (
            is_simple_execution(
                plan_wave_count=2,
                has_dag_dependencies=False,
                failed_steps=0,
                total_steps=1,
            )
            is False
        )

    def test_deps_not_simple(self) -> None:
        assert (
            is_simple_execution(
                plan_wave_count=1,
                has_dag_dependencies=True,
                failed_steps=0,
                total_steps=1,
            )
            is False
        )

    def test_failures_not_simple(self) -> None:
        assert (
            is_simple_execution(
                plan_wave_count=1,
                has_dag_dependencies=False,
                failed_steps=1,
                total_steps=1,
            )
            is False
        )

    def test_too_many_steps_not_simple(self) -> None:
        assert (
            is_simple_execution(
                plan_wave_count=1,
                has_dag_dependencies=False,
                failed_steps=0,
                total_steps=3,
            )
            is False
        )


class TestDagRequiresSynthesis:
    def test_replan_requires(self) -> None:
        assert (
            dag_requires_synthesis(
                plan_wave_count=2,
                failed_steps=0,
                completed_steps=1,
                chain_depth=1,
                last_wave_hit_subagent_cap=False,
                last_execute_wave_parallel_multi_step=False,
            )
            is True
        )

    def test_failed_steps_require(self) -> None:
        assert (
            dag_requires_synthesis(
                plan_wave_count=1,
                failed_steps=1,
                completed_steps=0,
                chain_depth=1,
                last_wave_hit_subagent_cap=False,
                last_execute_wave_parallel_multi_step=False,
            )
            is True
        )

    def test_deep_chain_requires(self) -> None:
        assert (
            dag_requires_synthesis(
                plan_wave_count=1,
                failed_steps=0,
                completed_steps=3,
                chain_depth=3,
                last_wave_hit_subagent_cap=False,
                last_execute_wave_parallel_multi_step=False,
            )
            is True
        )

    def test_simple_no_synthesis(self) -> None:
        assert (
            dag_requires_synthesis(
                plan_wave_count=1,
                failed_steps=0,
                completed_steps=1,
                chain_depth=1,
                last_wave_hit_subagent_cap=False,
                last_execute_wave_parallel_multi_step=False,
            )
            is False
        )


class TestDetermineGoalCompletionNeeds:
    def test_llm_only_true(self) -> None:
        assert determine_goal_completion_needs(True, "llm_only") is True

    def test_llm_only_false(self) -> None:
        assert determine_goal_completion_needs(False, "llm_only") is False

    def test_heuristic_only_parallel(self) -> None:
        assert (
            determine_goal_completion_needs(
                False, "heuristic_only", last_execute_wave_parallel_multi_step=True
            )
            is True
        )

    def test_heuristic_only_simple(self) -> None:
        assert determine_goal_completion_needs(False, "heuristic_only") is False

    def test_hybrid_llm_true_wins(self) -> None:
        assert determine_goal_completion_needs(True, "hybrid") is True

    def test_hybrid_llm_false_heuristic_true(self) -> None:
        assert (
            determine_goal_completion_needs(
                False, "hybrid", last_execute_wave_parallel_multi_step=True
            )
            is True
        )

    def test_hybrid_both_false(self) -> None:
        assert determine_goal_completion_needs(False, "hybrid") is False


class TestDetermineCompletionStrategy:
    def test_always_synthesize_mode(self) -> None:
        assert (
            determine_completion_strategy(
                plan_result_require_goal_completion=False,
                plan_wave_count=1,
                has_dag_dependencies=False,
                failed_steps=0,
                total_steps=1,
                completed_steps=1,
                chain_depth=1,
                last_wave_hit_subagent_cap=False,
                last_execute_wave_parallel_multi_step=False,
                final_response_mode="always_synthesize",
            )
            == "synthesize"
        )

    def test_simple_ledger_direct(self) -> None:
        assert (
            determine_completion_strategy(
                plan_result_require_goal_completion=False,
                plan_wave_count=1,
                has_dag_dependencies=False,
                failed_steps=0,
                total_steps=2,
                completed_steps=2,
                chain_depth=1,
                last_wave_hit_subagent_cap=False,
                last_execute_wave_parallel_multi_step=False,
            )
            == "ledger_direct"
        )

    def test_complex_requires_synthesize(self) -> None:
        assert (
            determine_completion_strategy(
                plan_result_require_goal_completion=True,
                plan_wave_count=1,
                has_dag_dependencies=False,
                failed_steps=0,
                total_steps=1,
                completed_steps=1,
                chain_depth=1,
                last_wave_hit_subagent_cap=False,
                last_execute_wave_parallel_multi_step=False,
            )
            == "synthesize"
        )


class TestLedgerHelpers:
    def test_is_rich_enough_empty(self) -> None:
        assert is_rich_enough("") is False

    def test_is_rich_enough_code_block(self) -> None:
        assert is_rich_enough("```python\nprint('hi')\n```") is True

    def test_is_rich_enough_many_lines(self) -> None:
        text = "\n".join(f"line {i}" for i in range(8))
        assert is_rich_enough(text) is True

    def test_is_rich_enough_short_text(self) -> None:
        assert is_rich_enough("short") is False

    def test_is_rich_enough_100_chars(self) -> None:
        assert is_rich_enough("x" * 100) is True

    def test_overlaps_with_no_plan_output(self) -> None:
        result = MagicMock()
        result.full_output = ""
        assert overlaps_with_plan_output("some text", result) is True

    def test_overlaps_with_matching_output(self) -> None:
        result = MagicMock()
        result.full_output = "This is a detailed report about database migration"
        assert overlaps_with_plan_output("database migration report here", result) is True

    def test_can_return_directly_not_rich(self) -> None:
        result = MagicMock()
        result.full_output = "output"
        assert can_return_directly_from_ledger("short", result) is False


# ═══════════════════════════════════════════════════════════════════════
# StepPlanningSubengine
# ═══════════════════════════════════════════════════════════════════════


class TestStepPlanningSubengineIngestPlan:
    def test_ingest_plan_adds_steps_to_goal(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        ce._dag.add_goal(goal)

        subengine = ce.planning.step
        steps = [
            _make_step_action("01", "Step 1"),
            _make_step_action("02", "Step 2", deps=["01"]),
        ]
        plan_result = _make_plan_result(steps)

        subengine.ingest_plan(goal.id, plan_result, "KFA", 0)

        goal_node = ce.get_goal_sync(goal.id)
        assert "01" in goal_node.steps.nodes
        assert "02" in goal_node.steps.nodes
        assert goal_node.steps.nodes["02"].dependencies == ["01"]
        assert len(subengine.plan_waves) == 1

    def test_ingest_plan_missing_goal_skips(self) -> None:
        ce = ContextEngine()
        subengine = ce.planning.step

        plan_result = _make_plan_result([_make_step_action("01", "S1")])
        subengine.ingest_plan("nonexistent", plan_result, "KFA", 0)

        assert len(subengine.plan_waves) == 1  # wave recorded even if goal missing

    def test_ingest_plan_no_decision_skips_steps(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        ce._dag.add_goal(goal)

        subengine = ce.planning.step
        plan_result = _make_plan_result(plan_action="keep")  # no decision
        subengine.ingest_plan(goal.id, plan_result, "KFA", 0)

        goal_node = ce.get_goal_sync(goal.id)
        assert goal_node.steps.total_steps == 0

    def test_ingest_plan_existing_step_keeps(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        ce._dag.add_goal(goal)

        subengine = ce.planning.step

        # First ingest
        steps = [_make_step_action("01", "Step 1")]
        subengine.ingest_plan(goal.id, _make_plan_result(steps), "KFA", 0)

        # Second ingest with same step ID (keep plan)
        subengine.ingest_plan(goal.id, _make_plan_result(steps), "KFA", 1)

        goal_node = ce.get_goal_sync(goal.id)
        assert goal_node.steps.total_steps == 1
        assert len(subengine.plan_waves) == 2


class TestStepPlanningSubengineRecordOutcomes:
    def test_record_success_and_failure(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        goal.steps.add_step(StepNode(id="01", description="S1"))
        goal.steps.add_step(StepNode(id="02", description="S2"))
        ce._dag.add_goal(goal)

        subengine = ce.planning.step
        subengine.record_step_outcomes(
            goal.id,
            [_make_step_result("01", success=True), _make_step_result("02", success=False)],
        )

        goal_node = ce.get_goal_sync(goal.id)
        assert goal_node.steps.nodes["01"].status == "completed"
        assert goal_node.steps.nodes["02"].status == "failed"

    def test_record_outcomes_missing_goal(self) -> None:
        ce = ContextEngine()
        subengine = ce.planning.step
        # Should not raise
        subengine.record_step_outcomes("nonexistent", [_make_step_result("01")])


class TestStepPlanningSubengineGetPlanningContext:
    def test_empty_for_missing_goal(self) -> None:
        ce = ContextEngine()
        subengine = ce.planning.step
        ctx = subengine.get_planning_context("nonexistent")
        assert isinstance(ctx, DagPlanningContext)
        assert ctx.total_steps == 0

    def test_context_with_steps(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        goal.steps.add_step(StepNode(id="01", description="S1", status="completed"))
        goal.steps.add_step(
            StepNode(id="02", description="S2", status="pending", dependencies=["01"])
        )
        ce._dag.add_goal(goal)

        subengine = ce.planning.step
        # Add a plan wave so replan_count is computed
        subengine._plan_waves.append(PlanWave(iteration=0, step_count=2))

        ctx = subengine.get_planning_context(goal.id)

        assert ctx.total_steps == 2
        assert ctx.completed_steps == 1
        assert "01" not in ctx.pending_step_ids  # completed
        assert "02" in ctx.pending_step_ids
        assert "02" in ctx.ready_step_ids
        assert ctx.replan_count == 0


class TestStepPlanningSubengineDetermineGoalCompletionNeeds:
    def test_llm_only_mode(self) -> None:
        ce = ContextEngine()
        subengine = ce.planning.step
        state = _make_mock_state()

        assert subengine.determine_goal_completion_needs("missing", True, state, "llm_only") is True
        assert (
            subengine.determine_goal_completion_needs("missing", False, state, "llm_only") is False
        )

    def test_heuristic_with_parallel(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        ce._dag.add_goal(goal)

        subengine = ce.planning.step
        state = _make_mock_state(last_execute_wave_parallel_multi_step=True)

        assert (
            subengine.determine_goal_completion_needs(goal.id, False, state, "heuristic_only")
            is True
        )


class TestStepPlanningSubengineFormatCompletionDagReport:
    def test_empty_for_missing_goal(self) -> None:
        ce = ContextEngine()
        subengine = ce.planning.step
        assert subengine.format_completion_dag_report("nonexistent") == ""

    def test_empty_for_no_goals(self) -> None:
        ce = ContextEngine()
        subengine = ce.planning.step
        assert subengine.format_completion_dag_report() == ""

    def test_single_goal_report(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        goal.steps.add_step(StepNode(id="01", description="S1", status="completed"))
        goal.steps.add_step(StepNode(id="02", description="S2", status="failed"))
        ce._dag.add_goal(goal)

        subengine = ce.planning.step
        subengine._plan_waves.append(PlanWave(iteration=0, step_count=2))

        report = subengine.format_completion_dag_report(goal.id)
        assert "Execution statistics" in report
        assert "COMPLETED" in report
        assert "FAILED" in report
        assert "01" in report
        assert "02" in report

    def test_hierarchical_report(self) -> None:
        ce = ContextEngine()
        g1 = GoalNode(description="Goal 1", status="completed")
        g1.steps.add_step(StepNode(id="S1", description="Step 1", status="completed"))
        g2 = GoalNode(description="Goal 2", status="active")
        ce._dag.add_goal(g1)
        ce._dag.add_goal(g2)

        subengine = ce.planning.step
        report = subengine.format_completion_dag_report()
        assert "Context Engine Goal DAG" in report
        assert "Goal statistics" in report
        assert "Total goals: 2" in report

    def test_hierarchical_report_with_lineage(self) -> None:
        ce = ContextEngine()
        parent = GoalNode(description="Parent goal")
        child = GoalNode(
            id="child-1",
            description="Child goal",
            parent_id=parent.id,
            source="decomposition",
        )
        child.steps.add_step(StepNode(id="S1", description="Sub-step", status="completed"))
        ce._dag.add_goal(parent)
        ce._dag.add_goal(child)

        subengine = ce.planning.step
        report = subengine.format_completion_dag_report()
        assert "child-1" in report
        assert "Lineage:" in report


# ═══════════════════════════════════════════════════════════════════════
# StepPlanManagerAdapter
# ═══════════════════════════════════════════════════════════════════════


class TestStepPlanManagerAdapter:
    def test_ingest_plan_delegates(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        ce._dag.add_goal(goal)

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        steps = [_make_step_action("01", "S1")]
        adapter.ingest_plan(_make_plan_result(steps), "KFA", 0)

        assert len(adapter.plan_history) == 1
        goal_node = ce.get_goal_sync(goal.id)
        assert "01" in goal_node.steps.nodes

    def test_ingest_plan_accumulates_history(self) -> None:
        ce = ContextEngine()
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id="")

        adapter.ingest_plan(_make_plan_result([_make_step_action("01", "S1")]), "A", 0)
        adapter.ingest_plan(_make_plan_result([_make_step_action("02", "S2")]), "B", 1)

        assert len(adapter.plan_history) == 2

    def test_record_step_outcomes_delegates(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        goal.steps.add_step(StepNode(id="01", description="S1"))
        goal.steps.add_step(StepNode(id="02", description="S2"))
        ce._dag.add_goal(goal)

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        adapter.record_step_outcomes(
            [_make_step_result("01", success=True), _make_step_result("02", success=False)]
        )

        goal_node = ce.get_goal_sync(goal.id)
        assert goal_node.steps.nodes["01"].status == "completed"
        assert goal_node.steps.nodes["02"].status == "failed"

    def test_get_planning_context_delegates(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        goal.steps.add_step(StepNode(id="01", description="S1", status="completed"))
        ce._dag.add_goal(goal)

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        ctx = adapter.get_planning_context()
        assert isinstance(ctx, DagPlanningContext)
        assert ctx.total_steps == 1
        assert ctx.completed_steps == 1

    def test_get_planning_context_empty_goal_id(self) -> None:
        ce = ContextEngine()
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id="")
        ctx = adapter.get_planning_context()
        assert ctx.total_steps == 0
        assert ctx.has_prior_state is False

    def test_determine_goal_completion_needs_delegates(self) -> None:
        ce = ContextEngine()
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id="")
        state = _make_mock_state()

        assert adapter.determine_goal_completion_needs(True, state, "llm_only") is True
        assert adapter.determine_goal_completion_needs(False, state, "llm_only") is False

    def test_determine_completion_strategy_delegates(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        ce._dag.add_goal(goal)

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        plan_result = _make_plan_result(require_goal_completion=False)
        state = _make_mock_state()

        strategy = adapter.determine_completion_strategy(state, plan_result, "adaptive")
        # With simple execution + no goal completion required → ledger_direct
        assert strategy.value == "ledger_direct"

    def test_format_completion_dag_report_delegates(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        goal.steps.add_step(StepNode(id="01", description="S1", status="completed"))
        ce._dag.add_goal(goal)

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        adapter.ingest_plan(_make_plan_result([_make_step_action("01", "S1")]), "KFA", 0)

        report = adapter.format_completion_dag_report()
        assert "Goal statistics" in report

    def test_format_completion_dag_report_empty(self) -> None:
        ce = ContextEngine()
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id="")
        assert adapter.format_completion_dag_report() == ""

    def test_goal_id_property(self) -> None:
        ce = ContextEngine()
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id="")
        assert adapter.goal_id is None  # empty string → None

        adapter.goal_id = "abc123"
        assert adapter.goal_id == "abc123"

    def test_dag_planning_context_has_all_nine_fields(self) -> None:
        """Verify the DagPlanningContext from adapter works with _format_dag_context."""
        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        goal.steps.add_step(StepNode(id="KFA-01", description="S1", status="completed"))
        goal.steps.add_step(
            StepNode(id="KFA-02", description="S2", status="pending", dependencies=["KFA-01"])
        )
        ce._dag.add_goal(goal)

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)

        ctx = adapter.get_planning_context()
        assert isinstance(ctx.has_prior_state, bool)
        assert isinstance(ctx.total_steps, int)
        assert isinstance(ctx.completed_steps, int)
        assert isinstance(ctx.failed_step_ids, set)
        assert isinstance(ctx.ready_step_ids, set)
        assert isinstance(ctx.pending_step_ids, set)
        assert isinstance(ctx.chain_depth, int)
        assert isinstance(ctx.success_rate, float)
        assert isinstance(ctx.replan_count, int)

    def test_format_dag_context_produces_text(self) -> None:
        """Verify the DagPlanningContext from adapter works with _format_dag_context."""
        from soothe.foundation.loop.prompts.builder import _format_dag_context

        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        goal.steps.add_step(StepNode(id="KFA-01", description="S1", status="completed"))
        goal.steps.add_step(StepNode(id="KFA-02", description="S2", status="pending"))
        ce._dag.add_goal(goal)

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)

        ctx = adapter.get_planning_context()
        text = _format_dag_context(ctx)

        assert "Total steps planned: 2" in text
        assert "KFA-02" in text

    def test_format_dag_context_empty_when_no_prior_state(self) -> None:
        from soothe.foundation.loop.prompts.builder import _format_dag_context

        ce = ContextEngine()
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id="")
        ctx = adapter.get_planning_context()
        text = _format_dag_context(ctx)
        assert text == ""


# ═══════════════════════════════════════════════════════════════════════
# GoalScheduler
# ═══════════════════════════════════════════════════════════════════════


class TestGoalSchedulerReadyGoals:
    def test_no_goals(self) -> None:
        ce = ContextEngine()
        scheduler = ce.planning.scheduler
        assert scheduler.peek_ready_goals() == []

    def test_pending_goal_is_ready(self) -> None:
        ce = ContextEngine()
        g = GoalNode(description="Ready goal", status="pending")
        ce._dag.add_goal(g)

        scheduler = ce.planning.scheduler
        ready = scheduler.peek_ready_goals()
        assert len(ready) == 1
        assert ready[0].id == g.id

    def test_active_goal_not_ready(self) -> None:
        ce = ContextEngine()
        g = GoalNode(description="Active goal", status="active")
        ce._dag.add_goal(g)

        scheduler = ce.planning.scheduler
        assert scheduler.peek_ready_goals() == []

    def test_limit_respected(self) -> None:
        ce = ContextEngine()
        for i in range(5):
            ce._dag.add_goal(GoalNode(description=f"Goal {i}", status="pending", priority=50))

        scheduler = ce.planning.scheduler
        assert len(scheduler.peek_ready_goals(limit=2)) == 2


class TestGoalSchedulerClaimGoal:
    def test_claim_pending_goal(self) -> None:
        ce = ContextEngine()
        g = GoalNode(description="Ready goal", status="pending")
        ce._dag.add_goal(g)

        scheduler = ce.planning.scheduler
        claimed = scheduler.claim_goal(g.id, loop_id="loop-1")

        assert claimed is not None
        assert claimed.status == "active"
        assert claimed.assigned_loop_id == "loop-1"

    def test_claim_nonexistent(self) -> None:
        ce = ContextEngine()
        scheduler = ce.planning.scheduler
        assert scheduler.claim_goal("nonexistent") is None

    def test_claim_non_pending(self) -> None:
        ce = ContextEngine()
        g = GoalNode(description="Active", status="active")
        ce._dag.add_goal(g)

        scheduler = ce.planning.scheduler
        assert scheduler.claim_goal(g.id) is None

    def test_claim_with_active_conflict(self) -> None:
        ce = ContextEngine()
        g1 = GoalNode(description="Active", status="active")
        g2 = GoalNode(description="Conflicting", status="pending", conflicts_with=[g1.id])
        ce._dag.add_goal(g1)
        ce._dag.add_goal(g2)

        scheduler = ce.planning.scheduler
        assert scheduler.claim_goal(g2.id) is None

    def test_claim_with_unmet_dependency(self) -> None:
        ce = ContextEngine()
        g1 = GoalNode(description="Pending dep", status="pending")
        g2 = GoalNode(description="Waiting goal", status="pending", depends_on=[g1.id])
        ce._dag.add_goal(g1)
        ce._dag.add_goal(g2)

        scheduler = ce.planning.scheduler
        assert scheduler.claim_goal(g2.id) is None


class TestGoalSchedulerIsComplete:
    def test_empty_is_complete(self) -> None:
        ce = ContextEngine()
        scheduler = ce.planning.scheduler
        assert scheduler.is_complete() is True

    def test_all_terminal_is_complete(self) -> None:
        ce = ContextEngine()
        ce._dag.add_goal(GoalNode(description="Done", status="completed"))
        ce._dag.add_goal(GoalNode(description="Failed", status="failed"))

        scheduler = ce.planning.scheduler
        assert scheduler.is_complete() is True

    def test_active_is_not_complete(self) -> None:
        ce = ContextEngine()
        ce._dag.add_goal(GoalNode(description="Active", status="active"))

        scheduler = ce.planning.scheduler
        assert scheduler.is_complete() is False


class TestGoalSchedulerCheckReactivatable:
    def test_blocked_with_met_deps(self) -> None:
        ce = ContextEngine()
        g1 = GoalNode(description="Completed dep", status="completed")
        g2 = GoalNode(description="Blocked goal", status="blocked", depends_on=[g1.id])
        ce._dag.add_goal(g1)
        ce._dag.add_goal(g2)

        scheduler = ce.planning.scheduler
        reactivatable = scheduler.check_reactivatable_goals()
        assert len(reactivatable) == 1
        assert reactivatable[0].id == g2.id

    def test_no_reactivatable(self) -> None:
        ce = ContextEngine()
        ce._dag.add_goal(GoalNode(description="Active", status="active"))
        ce._dag.add_goal(GoalNode(description="Completed", status="completed"))

        scheduler = ce.planning.scheduler
        assert scheduler.check_reactivatable_goals() == []


# ═══════════════════════════════════════════════════════════════════════
# GoalPlanningSubengine
# ═══════════════════════════════════════════════════════════════════════


class TestGoalPlanningSubengineDecompose:
    @pytest.mark.asyncio
    async def test_stub_returns_empty(self) -> None:
        ce = ContextEngine()
        planner = ce.planning.goal

        result = await planner.decompose_goal(
            DecompositionRequest(
                goal_description="Complex objective",
                goal_id="g1",
                context_summary="",
            )
        )
        assert result.subgoals == []
        assert result.reasoning == "Not yet implemented"


class TestGoalPlanningSubengineCreateSubgoals:
    def test_creates_child_goals(self) -> None:
        ce = ContextEngine()
        parent = GoalNode(description="Parent goal")
        ce._dag.add_goal(parent)

        planner = ce.planning.goal
        result = DecompositionResult(
            subgoals=[
                SubGoalSpec(description="Child 1", priority=80),
                SubGoalSpec(description="Child 2", priority=60, depends_on=["0"]),
            ],
            reasoning="Split by concern",
            strategy="mixed",
        )

        created = planner.create_subgoals(parent.id, result)
        assert len(created) == 2
        assert created[0].parent_id == parent.id
        assert created[0].source == "decomposition"
        assert created[1].depends_on  # depends on child 0

    def test_empty_subgoals(self) -> None:
        ce = ContextEngine()
        parent = GoalNode(description="Parent goal")
        ce._dag.add_goal(parent)

        planner = ce.planning.goal
        result = DecompositionResult(subgoals=[], reasoning="None")
        assert planner.create_subgoals(parent.id, result) == []


class TestGoalPlanningSubengineOrchestration:
    def test_empty_dag(self) -> None:
        ce = ContextEngine()
        planner = ce.planning.goal
        strategy = planner.compute_orchestration_strategy()
        assert strategy.concurrency_mode == "adaptive"  # default for empty

    def test_sequential_dag(self) -> None:
        ce = ContextEngine()
        g1 = GoalNode(description="G1", status="pending")
        g2 = GoalNode(description="G2", status="pending", depends_on=[g1.id])
        ce._dag.add_goal(g1)
        ce._dag.add_goal(g2)

        planner = ce.planning.goal
        strategy = planner.compute_orchestration_strategy()
        # g1 has no deps (parallel flag), g2 has deps (sequential flag) → mixed
        assert strategy.concurrency_mode == "mixed"

    def test_parallel_dag(self) -> None:
        ce = ContextEngine()
        g1 = GoalNode(description="G1", status="pending")
        g2 = GoalNode(description="G2", status="pending")
        ce._dag.add_goal(g1)
        ce._dag.add_goal(g2)

        planner = ce.planning.goal
        strategy = planner.compute_orchestration_strategy()
        assert strategy.concurrency_mode == "parallel"

    def test_purely_sequential_all_deps(self) -> None:
        """All goals have dependencies → sequential."""
        ce = ContextEngine()
        g1 = GoalNode(description="G1", status="completed")
        g2 = GoalNode(description="G2", status="pending", depends_on=[g1.id])
        ce._dag.add_goal(g1)
        ce._dag.add_goal(g2)

        planner = ce.planning.goal
        strategy = planner.compute_orchestration_strategy()
        # No pending goals without deps, but g2 has deps → sequential
        assert strategy.concurrency_mode == "sequential"

    def test_mixed_dag(self) -> None:
        ce = ContextEngine()
        g1 = GoalNode(description="G1", status="pending")
        g2 = GoalNode(description="G2", status="pending")
        g3 = GoalNode(description="G3", status="pending", depends_on=[g1.id])
        ce._dag.add_goal(g1)
        ce._dag.add_goal(g2)
        ce._dag.add_goal(g3)

        planner = ce.planning.goal
        strategy = planner.compute_orchestration_strategy()
        assert strategy.concurrency_mode == "mixed"


class TestGoalPlanningSubengineReflect:
    @pytest.mark.asyncio
    async def test_stub_returns_empty(self) -> None:
        ce = ContextEngine()
        planner = ce.planning.goal
        result = await planner.reflect_and_create_goals("g1")
        assert result == []

    def test_suggest_adjustments_stub(self) -> None:
        ce = ContextEngine()
        planner = ce.planning.goal
        assert planner.suggest_goal_adjustments("g1") == []


# ═══════════════════════════════════════════════════════════════════════
# PlanningFacade
# ═══════════════════════════════════════════════════════════════════════


class TestPlanningFacade:
    def test_facade_has_subengines(self) -> None:
        ce = ContextEngine()
        facade = ce.planning

        assert isinstance(facade, PlanningFacade)
        assert isinstance(facade.step, StepPlanningSubengine)
        assert isinstance(facade.goal, GoalPlanningSubengine)
        assert isinstance(facade.scheduler, GoalScheduler)

    def test_facade_shares_dag(self) -> None:
        ce = ContextEngine()
        facade = ce.planning

        # All subengines share the same DAG
        assert facade.step._dag is facade.scheduler._dag
        assert facade.step._dag is facade.goal._dag


# ═══════════════════════════════════════════════════════════════════════
# Planning models
# ═══════════════════════════════════════════════════════════════════════


class TestPlanningModels:
    def test_plan_wave_defaults(self) -> None:
        wave = PlanWave()
        assert wave.plan_id is None
        assert wave.iteration == 0
        assert wave.step_count == 0

    def test_sub_goal_spec_defaults(self) -> None:
        spec = SubGoalSpec(description="Test subgoal")
        assert spec.priority == 50
        assert spec.depends_on == []
        assert spec.conflicts_with == []

    def test_decomposition_request(self) -> None:
        req = DecompositionRequest(
            goal_description="Complex goal",
            goal_id="g1",
            context_summary="some context",
        )
        assert req.max_subgoals == 5
        assert req.constraints == []

    def test_decomposition_result_strategy(self) -> None:
        result = DecompositionResult(subgoals=[], reasoning="test")
        assert result.strategy == "parallel"

    def test_orchestration_strategy_defaults(self) -> None:
        strategy = OrchestrationStrategy()
        assert strategy.concurrency_mode == "adaptive"
        assert strategy.dependency_graph == {}


def test_completion_constants_single_source() -> None:
    """Constants live in completion.py (single source of truth)."""
    assert DAG_DEPENDENCY_THRESHOLD == 3
    assert LOW_SUCCESS_RATE_THRESHOLD == 0.6
    assert SIMPLE_DAG_LEDGER_DIRECT_MAX_STEPS == 2
    assert STRUCTURED_PAYLOAD_MIN_LINES == 6
