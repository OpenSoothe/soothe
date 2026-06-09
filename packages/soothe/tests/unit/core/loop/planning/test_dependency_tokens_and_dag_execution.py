"""Unified DAG + dependency token expansion (IG-400, cross-iteration readiness)."""

from __future__ import annotations

from soothe.foundation.loop.planning.dag import PlanDAG
from soothe.foundation.loop.planning.dependency_tokens import expand_dependency_satisfaction_ids
from soothe.foundation.loop.planning.manager import PlanManager
from soothe.foundation.loop.state.schemas import (
    AgentDecision,
    PlanResult,
    StepAction,
    StepResult,
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
        """Two completed steps ending in numeric value 1 → do not add bare ``1`` / ``01``."""
        out = expand_dependency_satisfaction_ids({"ABC-01", "DEF-01"})
        assert out == {"ABC-01", "DEF-01"}

    def test_different_int_values_both_expand_independently(self) -> None:
        out = expand_dependency_satisfaction_ids({"P-01", "P-02"})
        assert "01" in out
        assert "1" in out
        assert "02" in out
        assert "2" in out


class TestAgentDecisionCrossIterationReady:
    """Regression: second-wave steps depend on ``01`` while history has ``PLAN-01``."""

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


class TestPlanDagIngestAndMarkCompleted:
    def test_ingest_scoped_ids_then_mark_completed_matches_step_result(self) -> None:
        """DAG keys must match ``StepResult.step_id`` (composite after resolve)."""
        dag = PlanDAG()
        pr = PlanResult(
            status="continue",
            goal_progress="low",
            plan_action="new",
            decision=AgentDecision(
                type="execute_steps",
                steps=[
                    StepAction(id="KFA-01", description="first", expected_output="o"),
                ],
                execution_mode="parallel",
                reasoning="r",
            ),
            next_action="go",
        )
        dag.ingest_plan(pr, "KFA", 0)
        assert "KFA-01" in dag.nodes
        sr = StepResult(
            step_id="KFA-01",
            success=True,
            outcome={"type": "generic"},
            duration_ms=1,
            thread_id="t",
        )
        dag.mark_completed("KFA-01", sr)
        assert dag.nodes["KFA-01"].status == "completed"
        assert "KFA-01" in dag.get_completed_step_ids()

    def test_ready_step_ids_cross_wave_local_dependency(self) -> None:
        dag = PlanDAG()
        dag.ingest_plan(
            PlanResult(
                status="continue",
                goal_progress="low",
                plan_action="new",
                decision=AgentDecision(
                    type="execute_steps",
                    steps=[StepAction(id="AAA-01", description="bootstrap", expected_output="o")],
                    execution_mode="parallel",
                    reasoning="r",
                ),
                next_action="a",
            ),
            "AAA",
            0,
        )
        dag.mark_completed(
            "AAA-01",
            StepResult(
                step_id="AAA-01",
                success=True,
                outcome={"type": "generic"},
                duration_ms=1,
                thread_id="t",
            ),
        )
        dag.ingest_plan(
            PlanResult(
                status="continue",
                goal_progress="medium",
                plan_action="new",
                decision=AgentDecision(
                    type="execute_steps",
                    steps=[
                        StepAction(
                            id="BBB-03",
                            description="follow",
                            expected_output="o",
                            dependencies=["01"],
                        ),
                    ],
                    execution_mode="parallel",
                    reasoning="r",
                ),
                next_action="b",
            ),
            "BBB",
            1,
        )
        assert "BBB-03" in dag.ready_step_ids


class TestPlanManagerIngestRecordFlow:
    def test_record_step_outcomes_updates_dag(self) -> None:
        pm = PlanManager(goal="g")
        pr = PlanResult(
            status="continue",
            goal_progress="low",
            plan_action="new",
            decision=AgentDecision(
                type="execute_steps",
                steps=[StepAction(id="ZZZ-01", description="s", expected_output="o")],
                execution_mode="parallel",
                reasoning="r",
            ),
            next_action="n",
        )
        pm.ingest_plan(pr, "ZZZ", 0)
        pm.record_step_outcomes(
            [
                StepResult(
                    step_id="ZZZ-01",
                    success=True,
                    outcome={"type": "generic"},
                    duration_ms=1,
                    thread_id="t",
                )
            ]
        )
        assert pm.dag.completed_steps == 1


class TestPlanDagMaxChainDepthExternalSatisfied:
    def test_dependency_on_completed_external_id_does_not_inflate_depth(self) -> None:
        dag = PlanDAG()
        dag.ingest_plan(
            PlanResult(
                status="continue",
                goal_progress="low",
                plan_action="new",
                decision=AgentDecision(
                    type="execute_steps",
                    steps=[StepAction(id="M-01", description="root", expected_output="o")],
                    execution_mode="parallel",
                    reasoning="r",
                ),
                next_action="x",
            ),
            "M",
            0,
        )
        dag.mark_completed(
            "M-01",
            StepResult(
                step_id="M-01",
                success=True,
                outcome={"type": "generic"},
                duration_ms=1,
                thread_id="t",
            ),
        )
        dag.ingest_plan(
            PlanResult(
                status="continue",
                goal_progress="low",
                plan_action="new",
                decision=AgentDecision(
                    type="execute_steps",
                    steps=[
                        StepAction(
                            id="M-02",
                            description="child",
                            expected_output="o",
                            dependencies=["01"],
                        ),
                    ],
                    execution_mode="parallel",
                    reasoning="r",
                ),
                next_action="y",
            ),
            "M",
            1,
        )
        # Without satisfied-dep handling, ``01`` is not a node key and depth math breaks.
        assert dag.max_chain_depth >= 1
