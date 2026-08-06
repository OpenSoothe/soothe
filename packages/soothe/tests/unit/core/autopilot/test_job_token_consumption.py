"""Tests for Autopilot CE job token accounting (IG-701)."""

from __future__ import annotations

import pytest

from soothe.autopilot import AutopilotService
from soothe.config.models import AutopilotConfig
from soothe.context import ContextEngine
from soothe.context.models import StepExecution
from soothe.events.internal_bus import InternalEventBus


class _Factory:
    def create_runner(self, loop_id: str):  # noqa: ANN001
        raise AssertionError("dispatch not expected")


def _svc(ce: ContextEngine) -> AutopilotService:
    return AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=1),
        internal_bus=InternalEventBus(),
        runner_factory=_Factory(),
        subscribe_to_bus=False,
    )


@pytest.mark.asyncio
async def test_step_token_delta_from_cumulative_cursor() -> None:
    ce = ContextEngine()
    svc = _svc(ce)
    goal = await ce.create_goal("root", priority=50)
    await svc._mirror_plan_decision(
        goal.id,
        {
            "iteration": 0,
            "steps": [
                {"id": "S-01", "description": "a", "dependencies": []},
                {"id": "S-02", "description": "b", "dependencies": ["S-01"]},
            ],
        },
    )
    await svc._mirror_step_completed(
        goal.id,
        {
            "step_id": "S-01",
            "success": True,
            "duration_ms": 1,
            "total_tokens_used": 1000,
        },
    )
    await svc._mirror_step_completed(
        goal.id,
        {
            "step_id": "S-02",
            "success": True,
            "duration_ms": 1,
            "total_tokens_used": 2500,
        },
    )
    node = ce.get_goal_sync(goal.id)
    assert node is not None
    assert node.steps.nodes["S-01"].execution.tokens_used == 1000
    assert node.steps.nodes["S-02"].execution.tokens_used == 1500
    assert node.total_tokens_used == 2500


@pytest.mark.asyncio
async def test_explicit_tokens_used_delta_preferred() -> None:
    ce = ContextEngine()
    svc = _svc(ce)
    goal = await ce.create_goal("root", priority=50)
    await svc._mirror_plan_decision(
        goal.id,
        {"iteration": 0, "steps": [{"id": "S-01", "description": "a", "dependencies": []}]},
    )
    await svc._mirror_step_completed(
        goal.id,
        {
            "step_id": "S-01",
            "success": True,
            "tokens_used": 42,
            "total_tokens_used": 9999,
        },
    )
    node = ce.get_goal_sync(goal.id)
    assert node is not None
    assert node.total_tokens_used == 42


@pytest.mark.asyncio
async def test_goal_started_resets_cursor_for_new_attempt() -> None:
    ce = ContextEngine()
    svc = _svc(ce)
    goal = await ce.create_goal("root", priority=50)
    svc._goal_loop_token_cursor[goal.id] = 5000
    # Simulate new attempt: cursor reset then cumulative from 0.
    svc._goal_loop_token_cursor[goal.id] = 0
    await svc._mirror_plan_decision(
        goal.id,
        {"iteration": 0, "steps": [{"id": "S-01", "description": "a", "dependencies": []}]},
    )
    await svc._mirror_step_completed(
        goal.id,
        {"step_id": "S-01", "success": True, "total_tokens_used": 200},
    )
    node = ce.get_goal_sync(goal.id)
    assert node is not None
    assert node.total_tokens_used == 200


@pytest.mark.asyncio
async def test_subtree_total_tokens_sums_descendants() -> None:
    ce = ContextEngine()
    svc = _svc(ce)
    root = await ce.create_goal("job", priority=50)
    child = await ce.create_goal("child", priority=50, parent_id=root.id)
    root_node = ce.get_goal_sync(root.id)
    child_node = ce.get_goal_sync(child.id)
    assert root_node is not None and child_node is not None
    root_node.total_tokens_used = 100
    child_node.total_tokens_used = 400
    assert await svc.subtree_total_tokens(root.id) == 500
    dag = await svc.dag_snapshot(root.id)
    by_id = {n["id"]: n for n in dag["nodes"]}
    assert by_id[root.id]["total_tokens_used"] == 100
    assert by_id[child.id]["total_tokens_used"] == 400


@pytest.mark.asyncio
async def test_complete_step_accumulates_tokens() -> None:
    """CE complete_step remains the accumulator used by the mirror path."""
    ce = ContextEngine()
    goal = await ce.create_goal("g", priority=50)
    from soothe.context.models import StepNode

    g = ce.get_goal_sync(goal.id)
    assert g is not None
    g.steps.add_step(StepNode(id="1", description="x"))
    g.steps.add_step(StepNode(id="2", description="y"))
    await ce.complete_step(goal.id, "1", StepExecution(tokens_used=10))
    await ce.fail_step(goal.id, "2", StepExecution(tokens_used=5))
    fetched = ce.get_goal_sync(goal.id)
    assert fetched is not None
    assert fetched.total_tokens_used == 15
