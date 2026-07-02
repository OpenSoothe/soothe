"""Tests for cross-wave plan DAG normalization."""

from __future__ import annotations

from soothe.foundation.sloop.cognition.plan_dag_normalizer import normalize_plan_dag
from soothe.foundation.sloop.state.schemas import (
    AgentDecision,
    PlanGenerateStep,
    StepAction,
    plan_generate_steps_to_step_actions,
)


def test_resolves_bare_suffix_to_completed_composite() -> None:
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(
                id="03",
                description="Fix failures",
                dependencies=["01"],
            )
        ],
        execution_mode="parallel",
        reasoning="continue",
    )
    out = normalize_plan_dag(decision, completed_ids={"KFA-01"})
    assert out.steps[0].dependencies == ["KFA-01"]
    assert out.execution_mode == "dependency"


def test_keeps_in_plan_dependencies() -> None:
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="03", description="a"),
            StepAction(id="04", description="b", dependencies=["03"]),
        ],
        execution_mode="parallel",
        reasoning="chain",
    )
    out = normalize_plan_dag(decision, completed_ids=set())
    assert out.steps[1].dependencies == ["03"]
    assert out.execution_mode == "dependency"


def test_drops_unknown_dependency() -> None:
    decision = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="03", description="x", dependencies=["MISSING-99"])],
        execution_mode="parallel",
        reasoning="x",
    )
    out = normalize_plan_dag(decision, completed_ids={"KFA-01"})
    assert out.steps[0].dependencies is None
    assert out.execution_mode == "parallel"


def test_merges_continues_from_from_plan_generate_step() -> None:
    steps = plan_generate_steps_to_step_actions(
        [
            PlanGenerateStep(
                id="03",
                description="Add test",
                continues_from=["KFA-02"],
            )
        ]
    )
    assert steps[0].dependencies == ["KFA-02"]


def test_breaks_in_plan_cycle() -> None:
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="03", description="a", dependencies=["04"]),
            StepAction(id="04", description="b", dependencies=["03"]),
        ],
        execution_mode="dependency",
        reasoning="bad",
    )
    out = normalize_plan_dag(decision, completed_ids=set())
    dep_counts = sum(len(s.dependencies or []) for s in out.steps)
    assert dep_counts < 2
