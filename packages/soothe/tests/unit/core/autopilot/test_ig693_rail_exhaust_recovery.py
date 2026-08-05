"""IG-693: rail-bound send-back exhaustion → fail + retry_maker."""

from __future__ import annotations

import pytest

from soothe.autopilot.rail.builtins_exec import RailBuiltinExecutor, RailJobState
from soothe.autopilot.rail.guards import _structural_short_circuit
from soothe.context import ContextEngine


@pytest.mark.asyncio
async def test_rail_send_back_exhaust_fails_not_suspends() -> None:
    ce = ContextEngine()
    root = await ce.create_goal("job", priority=80, rail_id="greenfield-system")
    maker = await ce.create_goal(
        "maker",
        parent_id=root.id,
        priority=75,
        rail_id="greenfield-system",
    )
    maker.max_send_backs = 2
    maker.status = "active"
    for _ in range(2):
        updated = await ce.send_back_goal(maker.id, reason="thin evidence")
    assert updated.status == "failed"
    assert updated.send_back_count == 2


@pytest.mark.asyncio
async def test_non_rail_send_back_exhaust_suspends() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("solo", priority=50)
    goal.max_send_backs = 1
    goal.status = "active"
    updated = await ce.send_back_goal(goal.id, reason="thin evidence")
    assert updated.status == "suspended"
    assert updated.send_back_count == 1


def test_branch_is_stuck_short_circuit() -> None:
    structural = {
        "architecture_goal_ids": ["a1"],
        "pending_or_active_count": 0,
    }
    ok = _structural_short_circuit(
        condition_name="branch_is_stuck",
        event="goal_failed",
        trigger_tags=["maker", "implementation", "api"],
        structural=structural,
    )
    assert ok is not None and ok.matched is True

    no = _structural_short_circuit(
        condition_name="branch_is_stuck",
        event="goal_completed",
        trigger_tags=["maker"],
        structural=structural,
    )
    assert no is not None and no.matched is False


def test_wave_makers_done_requires_completed_not_failed() -> None:
    structural = {
        "architecture_goal_ids": ["a1"],
        "implementation_goal_ids": ["m1", "m2"],
        "all_implementation_terminal": True,
        "all_implementation_completed": False,
        "pending_or_active_count": 0,
    }
    blocked = _structural_short_circuit(
        condition_name="wave_makers_done",
        event="goal_completed",
        trigger_tags=["implementation", "maker"],
        structural=structural,
    )
    assert blocked is not None and blocked.matched is False

    ready = _structural_short_circuit(
        condition_name="wave_makers_done",
        event="goal_completed",
        trigger_tags=["implementation", "maker"],
        structural={**structural, "all_implementation_completed": True},
    )
    assert ready is not None and ready.matched is True


@pytest.mark.asyncio
async def test_retry_maker_replaces_only_failed() -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Build", priority=80)
    ex = RailBuiltinExecutor(ce)
    await ex.bind_job(
        RailJobState(job_id=root.id, rail_id="greenfield-system", rail_version="1.1", wave_index=1)
    )
    arch = await ce.create_goal("arch", parent_id=root.id, source="decomposition")
    await ce.complete_goal(arch.id)
    await ex.annotate_goal(arch.id, root.id, tags=["architecture", "planning"], role="planner")

    core = await ce.create_goal("core", parent_id=root.id, source="decomposition")
    await ce.complete_goal(core.id)
    await ex.annotate_goal(
        core.id, root.id, tags=["implementation", "maker", "wave-1", "core"], role="maker"
    )

    api = await ce.create_goal("api", parent_id=root.id, source="decomposition")
    await ce.fail_goal(api.id, error="send_back budget exhausted")
    await ex.annotate_goal(
        api.id, root.id, tags=["implementation", "maker", "wave-1", "api"], role="maker"
    )
    await ce.update_dependencies(root.id, [core.id, api.id])

    result = await ex.invoke("retry_maker", job_id=root.id, trigger_goal_id=api.id)
    assert result.status == "success"
    assert len(result.created_goal_ids) == 1
    new_id = result.created_goal_ids[0]
    new_g = await ce.get_goal(new_id)
    assert new_g is not None
    assert new_g.status == "pending"
    assert "api" in (new_g.rail_tags or [])
    assert "replant" in (new_g.rail_tags or [])

    refreshed = await ce.get_goal(root.id)
    assert refreshed is not None
    assert api.id not in (refreshed.depends_on or [])
    assert new_id in (refreshed.depends_on or [])
    assert core.id in (refreshed.depends_on or [])
    core_g = await ce.get_goal(core.id)
    assert core_g is not None and core_g.status == "completed"
