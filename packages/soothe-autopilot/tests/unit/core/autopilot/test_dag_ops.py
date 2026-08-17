"""IG-726 P2: bounded DAG ops from report-commit judgment."""

from __future__ import annotations

import pytest
from soothe.context.engine import ContextEngine

from soothe_autopilot.verify.dag_ops import DagOp, apply_bounded_dag_ops


@pytest.mark.asyncio
async def test_wire_and_priority_and_brief() -> None:
    ce = ContextEngine()
    a = await ce.create_goal("parent work", priority=50)
    b = await ce.create_goal("pending child", priority=40, parent_id=a.id)
    await ce.activate_goal(a.id, loop_id="w1")

    notes = await apply_bounded_dag_ops(
        ce,
        [
            DagOp(op="wire_depends", goal_id=b.id, depends_on=[a.id]),
            DagOp(op="set_priority", goal_id=b.id, priority=90),
            DagOp(
                op="update_pending_brief",
                goal_id=b.id,
                brief="pending child (revised after maker)",
            ),
        ],
        source_goal_id=a.id,
    )
    assert any(n.startswith("wired:") for n in notes)
    assert any(n.startswith("priority:") for n in notes)
    assert any(n.startswith("brief:") for n in notes)

    updated = await ce.get_goal(b.id)
    assert updated is not None
    assert a.id in updated.depends_on
    assert updated.priority == 90
    assert "revised after maker" in updated.description


@pytest.mark.asyncio
async def test_spawn_cancel_skipped_without_allowlist() -> None:
    ce = ContextEngine()
    g = await ce.create_goal("source")
    notes = await apply_bounded_dag_ops(
        ce,
        [
            DagOp(op="spawn_goal", brief="should not spawn"),
            DagOp(op="cancel_goal", goal_id=g.id),
        ],
        source_goal_id=g.id,
    )
    assert notes == [
        "skipped:spawn_goal:not_allowlisted",
        "skipped:cancel_goal:not_allowlisted",
    ]
    still = await ce.get_goal(g.id)
    assert still is not None
    assert still.status == "pending"


@pytest.mark.asyncio
async def test_spawn_allowed_when_allowlisted() -> None:
    ce = ContextEngine()
    g = await ce.create_goal("source")
    notes = await apply_bounded_dag_ops(
        ce,
        [DagOp(op="spawn_goal", brief="extra verify slice", priority=40)],
        source_goal_id=g.id,
        structural_allowlist=frozenset({"spawn_goal"}),
    )
    assert any(n.startswith("spawned:") for n in notes)
    spawned_id = next(n.split(":", 1)[1] for n in notes if n.startswith("spawned:"))
    child = await ce.get_goal(spawned_id)
    assert child is not None
    assert "extra verify slice" in child.description


@pytest.mark.asyncio
async def test_update_brief_rejects_non_pending() -> None:
    ce = ContextEngine()
    g = await ce.create_goal("active goal")
    await ce.activate_goal(g.id, loop_id="w1")
    notes = await apply_bounded_dag_ops(
        ce,
        [DagOp(op="update_pending_brief", goal_id=g.id, brief="nope")],
        source_goal_id=g.id,
    )
    assert notes == ["rejected:update_pending_brief:not_pending"]
