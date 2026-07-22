"""Tests for cross-wave plan DAG normalization."""

from __future__ import annotations

from soothe.sloop.cognition.plan_dag_normalizer import normalize_plan_dag
from soothe.sloop.state.schemas import (
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


def test_infers_linear_chain_when_dependency_mode_omits_edges() -> None:
    """Dependency mode without edges gets a stable 01→02→… chain (diagnose→fix)."""
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="01", description="Discover verification commands and run"),
            StepAction(
                id="02",
                description="Fix errors found in verification",
                full_description="Analyze errors from step 01 and apply fixes.",
            ),
        ],
        execution_mode="dependency",
        reasoning="I'll first run verification, then fix errors in a dependent step.",
    )
    out = normalize_plan_dag(decision, completed_ids=set())
    assert out.execution_mode == "dependency"
    assert out.steps[0].dependencies is None
    assert out.steps[1].dependencies == ["01"]


def test_infers_three_step_linear_chain() -> None:
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="01", description="Read"),
            StepAction(id="02", description="Analyze"),
            StepAction(id="03", description="Write"),
        ],
        execution_mode="dependency",
        reasoning="Sequential pipeline.",
    )
    out = normalize_plan_dag(decision, completed_ids=set())
    assert out.steps[0].dependencies is None
    assert out.steps[1].dependencies == ["01"]
    assert out.steps[2].dependencies == ["02"]


def test_does_not_infer_when_parallel_mode() -> None:
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="01", description="A"),
            StepAction(id="02", description="B"),
        ],
        execution_mode="parallel",
        reasoning="Independent work.",
    )
    out = normalize_plan_dag(decision, completed_ids=set())
    assert out.steps[0].dependencies is None
    assert out.steps[1].dependencies is None
    assert out.execution_mode == "parallel"


def test_fills_missing_tail_when_partial_dependencies() -> None:
    """Step 03 without deps chains to 02 when 02 already depends on 01."""
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="01", description="A"),
            StepAction(id="02", description="B", dependencies=["01"]),
            StepAction(id="03", description="C"),
        ],
        execution_mode="dependency",
        reasoning="Partial deps.",
    )
    out = normalize_plan_dag(decision, completed_ids=set())
    assert out.steps[1].dependencies == ["01"]
    assert out.steps[2].dependencies == ["02"]


def test_preserves_fan_in_when_step_declares_cross_predecessor() -> None:
    """Steps that already declare deps are not rewritten to a linear chain."""
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="01", description="A"),
            StepAction(id="02", description="B", dependencies=["01"]),
            StepAction(id="03", description="C", dependencies=["01"]),
        ],
        execution_mode="dependency",
        reasoning="Fan-in after shared read.",
    )
    out = normalize_plan_dag(decision, completed_ids=set())
    assert out.steps[1].dependencies == ["01"]
    assert out.steps[2].dependencies == ["01"]


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
