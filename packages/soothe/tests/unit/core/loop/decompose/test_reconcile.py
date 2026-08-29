"""Unit tests for deterministic decompose reconcile (IG-751 P2)."""

from __future__ import annotations

import pytest

from soothe.config.models import DecomposeLoopConfig
from soothe.context.decomposition import DecompositionProposal, ProposedSubtask
from soothe.context.engine import ContextEngine
from soothe.context.models import StepDAG, StepNode
from soothe.sloop.decompose.reconcile import (
    drain_executor_proposals,
    normalize_subtask_key,
    plan_commit_from_proposals,
    reconcile_proposals_deterministic,
)


def _cfg(**overrides: object) -> DecomposeLoopConfig:
    return DecomposeLoopConfig(**overrides)  # type: ignore[arg-type]


def test_normalize_subtask_key() -> None:
    assert normalize_subtask_key("  Foo   Bar ") == "foo bar"


def test_plan_commit_assigns_ids_and_marks_parents() -> None:
    dag = StepDAG(nodes={"ROOT": StepNode(id="ROOT", description="root", status="active")})
    proposals = [
        DecompositionProposal(
            parent_step_id="ROOT",
            subtasks=[
                ProposedSubtask(description="child A"),
                ProposedSubtask(description="child B", depends_on_local=[0]),
            ],
        )
    ]
    nodes, parents, rejected, plan_id = plan_commit_from_proposals(
        dag, proposals, config=_cfg(), plan_id="ABC"
    )
    assert not rejected
    assert parents == ["ROOT"]
    assert plan_id == "ABC"
    assert len(nodes) == 2
    assert {n.id for n in nodes} == {"ABC-01", "ABC-02"}
    by_desc = {n.description: n for n in nodes}
    assert by_desc["child A"].parent_step_id == "ROOT"
    assert by_desc["child B"].dependencies == [by_desc["child A"].id]


def test_branch_cap_truncates_root_overflow() -> None:
    """Over-cap proposals are truncated, not rejected."""
    dag = StepDAG(nodes={"ROOT": StepNode(id="ROOT", description="root", status="active")})
    proposals = [
        DecompositionProposal(
            parent_step_id="ROOT",
            subtasks=[ProposedSubtask(description=f"c{i}") for i in range(6)],
        )
    ]
    nodes, parents, rejected, _ = plan_commit_from_proposals(
        dag, proposals, config=_cfg(max_branch_root=5)
    )
    assert not rejected
    assert len(nodes) == 5  # truncated from 6 to 5


def test_inner_branch_cap_truncates() -> None:
    """Over-cap inner proposals are truncated, not rejected."""
    dag = StepDAG(
        nodes={
            "ROOT": StepNode(id="ROOT", description="root", status="decomposed"),
            "CHILD": StepNode(
                id="CHILD",
                description="inner",
                status="active",
                parent_step_id="ROOT",
            ),
        }
    )
    proposals = [
        DecompositionProposal(
            parent_step_id="CHILD",
            subtasks=[ProposedSubtask(description=f"c{i}") for i in range(4)],
        )
    ]
    nodes, parents, rejected, _ = plan_commit_from_proposals(
        dag, proposals, config=_cfg(max_branch_inner=3)
    )
    assert not rejected
    assert len(nodes) == 3  # truncated from 4 to 3


def test_max_depth_reject() -> None:
    dag = StepDAG(
        nodes={
            "R": StepNode(id="R", description="r", status="decomposed"),
            "A": StepNode(id="A", description="a", status="decomposed", parent_step_id="R"),
            "B": StepNode(id="B", description="b", status="active", parent_step_id="A"),
        }
    )
    # lineage_depth(B)=3; max_depth=3 → reject
    proposals = [
        DecompositionProposal(
            parent_step_id="B",
            subtasks=[ProposedSubtask(description="too deep")],
        )
    ]
    nodes, _, rejected, _ = plan_commit_from_proposals(dag, proposals, config=_cfg(max_depth=3))
    assert not nodes
    assert rejected[0].reason == "max_depth_exceeded"


def test_exact_dedup_secondary_parents() -> None:
    dag = StepDAG(
        nodes={
            "A": StepNode(id="A", description="a", status="active"),
            "B": StepNode(id="B", description="b", status="active"),
        }
    )
    proposals = [
        DecompositionProposal(
            parent_step_id="A",
            subtasks=[ProposedSubtask(description="Shared Work")],
        ),
        DecompositionProposal(
            parent_step_id="B",
            subtasks=[ProposedSubtask(description="shared   work")],
        ),
    ]
    nodes, parents, rejected, _ = plan_commit_from_proposals(
        dag, proposals, config=_cfg(), plan_id="XYZ"
    )
    assert not rejected
    assert set(parents) == {"A", "B"}
    assert len(nodes) == 1
    child = nodes[0]
    assert child.parent_step_id == "A"
    assert child.secondary_parent_step_ids == ["B"]


def test_max_steps_reject() -> None:
    dag = StepDAG(nodes={"ROOT": StepNode(id="ROOT", description="root", status="active")})
    proposals = [
        DecompositionProposal(
            parent_step_id="ROOT",
            subtasks=[
                ProposedSubtask(description="a"),
                ProposedSubtask(description="b"),
            ],
        )
    ]
    nodes, _, rejected, _ = plan_commit_from_proposals(dag, proposals, config=_cfg(max_steps=2))
    assert not nodes
    assert rejected[0].reason == "max_steps_exceeded"


def test_eval_reconcile_filters_out_of_scope_subtasks() -> None:
    dag = StepDAG(
        nodes={
            "EVAL": StepNode(
                id="EVAL",
                description="coverage",
                status="active",
                kind="eval",
            )
        }
    )
    proposal = DecompositionProposal(
        parent_step_id="EVAL",
        subtasks=[
            ProposedSubtask(description="required", in_scope=True, necessary_for_user_goal=True),
            ProposedSubtask(
                description="drive-by",
                in_scope=False,
                necessary_for_user_goal=False,
            ),
        ],
    )
    nodes, parents, rejected, _ = plan_commit_from_proposals(
        dag,
        [proposal],
        config=_cfg(),
        plan_id="EVL",
    )
    assert [node.description for node in nodes] == ["required"]
    assert parents == ["EVAL"]
    assert rejected[0].reason == "out_of_scope"


def test_eval_reconcile_rejects_identical_continuation() -> None:
    dag = StepDAG(
        nodes={
            "E1": StepNode(id="E1", description="first eval", status="decomposed", kind="eval"),
            "C1": StepNode(
                id="C1",
                description="same remaining work",
                status="completed",
                parent_step_id="E1",
            ),
            "E2": StepNode(id="E2", description="second eval", status="active", kind="eval"),
        }
    )
    proposal = DecompositionProposal(
        parent_step_id="E2",
        subtasks=[ProposedSubtask(description="same remaining work")],
    )
    nodes, parents, rejected, _ = plan_commit_from_proposals(
        dag,
        [proposal],
        config=_cfg(),
    )
    assert nodes == []
    assert parents == []
    assert rejected[-1].reason == "identical_eval_continuation"


@pytest.mark.asyncio
async def test_reconcile_commits_via_ce() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("do the work", loop_id="loop-p2")
    await ce.add_step(
        goal.id,
        StepNode(id="ROOT", description="root task", status="active"),
    )
    proposals = [
        DecompositionProposal(
            parent_step_id="ROOT",
            wave_seq=1,
            subtasks=[
                ProposedSubtask(
                    description="leaf A",
                    full_description="do A",
                    expected_output="A done",
                ),
                ProposedSubtask(description="leaf B"),
            ],
        )
    ]
    result = await reconcile_proposals_deterministic(
        ce,
        goal.id,
        proposals,
        config=_cfg(),
        plan_id="ABC",
    )
    assert not result.rejected
    assert result.llm_used is False
    assert result.decomposed_parent_ids == ["ROOT"]
    assert set(result.committed_step_ids) == {"ABC-01", "ABC-02"}

    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    assert refreshed.steps.nodes["ROOT"].status == "decomposed"
    ready = refreshed.steps.ready_steps()
    assert ready == {"ABC-01", "ABC-02"}


def test_drain_executor_proposals() -> None:
    class FakeExec:
        decompose_proposals: list = []

    ex = FakeExec()
    ex.decompose_proposals = [
        DecompositionProposal(
            parent_step_id="S1",
            subtasks=[ProposedSubtask(description="x")],
        )
    ]
    drained = drain_executor_proposals(ex)
    assert len(drained) == 1
    assert ex.decompose_proposals == []
