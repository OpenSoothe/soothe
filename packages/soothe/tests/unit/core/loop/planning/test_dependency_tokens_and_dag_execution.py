"""Unified StepDAG + dependency token expansion (IG-400, IG-537)."""

from __future__ import annotations

from soothe.context import StepPlanManagerAdapter
from soothe.context.dag_utils import expand_dependency_satisfaction_ids
from soothe.context.engine import ContextEngine
from soothe.context.models import GoalNode, StepExecution, StepNode
from soothe.sloop.state.schemas import (
    AgentDecision,
    PlanResult,
    StepAction,
    StepExecutionRecord,
)


class TestExpandDependencySatisfactionIds:
    def test_empty(self) -> None:
        assert expand_dependency_satisfaction_ids(set()) == set()

    def test_non_hyphen_ids_unchanged_except_copy(self) -> None:
        assert expand_dependency_satisfaction_ids({"abc", "def"}) == {"abc", "def"}

    def test_unique_numeric_suffix_adds_local_tokens(self) -> None:
        out = expand_dependency_satisfaction_ids({"KFA-01"})
        assert "KFA-01" in out
        assert "01" in out
        assert "1" in out

    def test_unique_multi_digit_suffix(self) -> None:
        out = expand_dependency_satisfaction_ids({"ZZZ-09"})
        assert "ZZZ-09" in out
        assert "09" in out
        assert "9" in out

    def test_ambiguous_same_int_two_composites_no_bare_suffix(self) -> None:
        out = expand_dependency_satisfaction_ids({"ABC-01", "DEF-01"})
        assert out == {"ABC-01", "DEF-01"}

    def test_different_int_values_both_expand_independently(self) -> None:
        out = expand_dependency_satisfaction_ids({"P-01", "P-02"})
        assert "01" in out
        assert "1" in out
        assert "02" in out
        assert "2" in out


class TestAgentDecisionCrossIterationReady:
    def test_local_dep_01_satisfied_by_prior_composite(self) -> None:
        prior_done = {"HJK-01"}
        wave2 = AgentDecision(
            type="execute_steps",
            steps=[
                StepAction(
                    id="HJK-03",
                    description="Read RFC group A",
                    expected_output="ok",
                    dependencies=["01"],
                ),
                StepAction(
                    id="HJK-04",
                    description="Read RFC group B",
                    expected_output="ok",
                    dependencies=["01"],
                ),
            ],
            execution_mode="parallel",
            reasoning="parallel after bootstrap",
        )
        ready = wave2.get_ready_steps(prior_done)
        assert {s.id for s in ready} == {"HJK-03", "HJK-04"}

    def test_local_dep_still_blocked_when_suffix_ambiguous(self) -> None:
        prior_done = {"ABC-01", "DEF-01"}
        wave2 = AgentDecision(
            type="execute_steps",
            steps=[
                StepAction(
                    id="XYZ-03",
                    description="blocked",
                    expected_output="x",
                    dependencies=["01"],
                ),
            ],
            execution_mode="parallel",
            reasoning="r",
        )
        assert wave2.get_ready_steps(prior_done) == []


def _make_adapter() -> StepPlanManagerAdapter:
    ce = ContextEngine()
    goal = GoalNode(description="g")
    ce._dag.add_goal(goal)
    return StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)


class TestStepPlanAdapterIngestRecordFlow:
    def test_ingest_then_record_outcomes(self) -> None:
        adapter = _make_adapter()
        pr = PlanResult(
            status="continue",
            goal_progress="low",
            plan_action="new",
            decision=AgentDecision(
                type="execute_steps",
                steps=[
                    StepAction(id="HJK-01", description="bootstrap"),
                    StepAction(id="HJK-02", description="follow", dependencies=["01"]),
                ],
                execution_mode="dependency",
            ),
            next_action="",
        )
        adapter.ingest_plan(pr, "HJK", 0)
        ctx = adapter.get_planning_context()
        assert ctx.total_steps == 2
        assert ctx.pending_step_ids == {"HJK-01", "HJK-02"}

        adapter.record_step_outcomes(
            [
                StepExecutionRecord(
                    step_id="HJK-01",
                    success=True,
                    outcome={},
                    duration_ms=1,
                    thread_id="t",
                )
            ]
        )
        ctx = adapter.get_planning_context()
        assert ctx.completed_steps == 1
        assert "HJK-02" in ctx.pending_step_ids

    def test_ready_steps_after_composite_completion(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="g")
        ce._dag.add_goal(goal)
        step_dag = goal.steps
        step_dag.add_step(StepNode(id="HJK-01", description="a"))
        step_dag.add_step(StepNode(id="HJK-02", description="b", dependencies=["01"]))
        step_dag.mark_completed("HJK-01", StepExecution())
        ready = step_dag.ready_steps()
        assert "HJK-02" in ready
