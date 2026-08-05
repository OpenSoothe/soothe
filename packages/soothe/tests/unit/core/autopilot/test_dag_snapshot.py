"""Tests for AutopilotService.dag_snapshot parent_id membership."""

from __future__ import annotations

import pytest

from soothe.autopilot import AutopilotService
from soothe.config.models import AutopilotConfig
from soothe.context import ContextEngine
from soothe.context.models import StepNode
from soothe.events.internal_bus import InternalEventBus

from .fakes import IdleFakeFactory


def _service() -> AutopilotService:
    return AutopilotService(
        ce=ContextEngine(),
        config=AutopilotConfig(max_loops=2, max_parallel_goals=2),
        internal_bus=InternalEventBus(),
        runner_factory=IdleFakeFactory(),
    )


@pytest.mark.asyncio
async def test_dag_snapshot_includes_parent_id_children() -> None:
    """Rail children use parent_id; root may depend_on the child (not inverted)."""
    svc = _service()
    root = await svc._ce.create_goal("job root", priority=70)
    child = await svc._ce.create_goal(
        "Architecture and milestone map",
        parent_id=root.id,
        source="decomposition",
        priority=80,
    )
    await svc._ce.update_dependencies(root.id, [child.id])
    await svc._ce.add_step(
        child.id,
        StepNode(id="ARC-01", description="List modules", status="pending"),
    )

    dag = await svc.dag_snapshot(root.id)
    ids = {n["id"] for n in dag["nodes"]}
    assert ids == {root.id, child.id}
    assert dag["root_id"] == root.id
    assert dag["edges"] == [{"source": root.id, "target": child.id}]

    by_id = {n["id"]: n for n in dag["nodes"]}
    assert by_id[child.id]["parent_id"] == root.id
    assert by_id[root.id]["depends_on"] == [child.id]
    assert by_id[child.id]["steps_total"] == 1
    assert by_id[child.id]["steps"]["nodes"][0]["id"] == "ARC-01"


@pytest.mark.asyncio
async def test_dag_snapshot_nested_parent_chain() -> None:
    svc = _service()
    root = await svc._ce.create_goal("root")
    mid = await svc._ce.create_goal("mid", parent_id=root.id)
    leaf = await svc._ce.create_goal("leaf", parent_id=mid.id)

    dag = await svc.dag_snapshot(root.id)
    assert {n["id"] for n in dag["nodes"]} == {root.id, mid.id, leaf.id}
    edges = {(e["source"], e["target"]) for e in dag["edges"]}
    assert edges == {(root.id, mid.id), (mid.id, leaf.id)}
