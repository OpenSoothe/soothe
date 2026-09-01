"""Unit tests for streaming slice spawn + WavePlan depends_on (IG-732)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from soothe.context import ContextEngine
from soothe.rails.builtins_exec import RailBuiltinExecutor, RailJobState
from soothe.rails.guards import GuardResult, _structural_short_circuit
from soothe.rails.wave_plan import WavePlan, apply_wave_plan_to_state_fields


def test_wave_plan_depends_on_accept() -> None:
    plan = WavePlan.model_validate(
        {
            "slices": [
                {"slice": "auth", "description": "auth"},
                {"slice": "chat", "description": "chat", "depends_on": ["auth"]},
            ],
            "independence": "chat waits on auth",
        }
    )
    assert plan.resolved_slice_ids() == ["auth", "chat"]
    decomp = plan.as_decompose_plan()
    assert decomp is not None
    assert decomp[1]["depends_on"] == ["auth"]
    updates = apply_wave_plan_to_state_fields(plan)
    assert updates["wave_slices"] == ["auth", "chat"]


def test_wave_plan_depends_on_unknown_rejects() -> None:
    with pytest.raises(ValidationError):
        WavePlan.model_validate(
            {
                "slices": [
                    {"slice": "a", "depends_on": ["missing"]},
                ]
            }
        )


def test_wave_plan_depends_on_cycle_rejects() -> None:
    with pytest.raises(ValidationError):
        WavePlan.model_validate(
            {
                "slices": [
                    {"slice": "a", "depends_on": ["b"]},
                    {"slice": "b", "depends_on": ["a"]},
                ]
            }
        )


@pytest.mark.asyncio
async def test_spawn_ready_respects_depends_on() -> None:
    ce = ContextEngine()
    ex = RailBuiltinExecutor(ce)
    job = await ce.create_goal("job", source="decomposition", priority=50)
    arch = await ce.create_goal("arch", parent_id=job.id, source="decomposition", priority=80)
    await ce.complete_goal(arch.id)
    state = RailJobState(
        job_id=job.id,
        rail_id="greenfield-system",
        rail_version="1.14",
        require_plan=True,
        fanout_enabled=True,
        worktrees_enabled=False,
        max_slices=16,
        wave_slices=["auth", "chat", "shell"],
        decompose_plan=[
            {"slice": "auth", "description": "auth", "tags": ["implementation", "maker"]},
            {
                "slice": "chat",
                "description": "chat",
                "tags": ["implementation", "maker"],
                "depends_on": ["auth"],
            },
            {"slice": "shell", "description": "shell", "tags": ["implementation", "maker"]},
        ],
    )
    await ex.bind_job(state)
    await ex.annotate_goal(
        arch.id,
        job.id,
        tags=["architecture", "planning"],
        role="planner",
    )

    first = await ex.invoke("spawn_wave_makers", job_id=job.id)
    assert first.status == "success"
    assert len(first.created_goal_ids) == 2  # auth + shell; chat waits
    st = await ex.job_state(job.id)
    assert st is not None
    assert "auth" in st.spawned_slices
    assert "shell" in st.spawned_slices
    assert "chat" not in st.spawned_slices

    # Complete auth → chat becomes ready.
    auth_gid = st.spawned_slices["auth"]
    await ce.complete_goal(auth_gid)
    second = await ex.invoke("spawn_wave_makers", job_id=job.id)
    assert second.status == "success"
    st2 = await ex.job_state(job.id)
    assert st2 is not None
    assert "chat" in st2.spawned_slices


def test_slices_ready_to_spawn_guard() -> None:
    structural = {
        "all_architecture_terminal": True,
        "require_plan": True,
        "wave_plan_ready": True,
        "slices_ready_unspawned": True,
        "below_slice_budget": True,
        "implementation_goal_ids": ["m1"],
    }
    r = _structural_short_circuit(
        condition_name="slices_ready_to_spawn",
        event="goal_completed",
        trigger_tags=["implementation"],
        structural=structural,
    )
    assert isinstance(r, GuardResult)
    assert r.matched is True

    blocked = _structural_short_circuit(
        condition_name="slices_ready_to_spawn",
        event="goal_completed",
        trigger_tags=["implementation"],
        structural={**structural, "slices_ready_unspawned": False},
    )
    assert blocked is not None and blocked.matched is False


def test_maker_needs_merge_guard() -> None:
    r = _structural_short_circuit(
        condition_name="maker_needs_merge",
        event="goal_completed",
        trigger_tags=["implementation", "maker"],
        structural={"trigger_needs_merge": True},
    )
    assert r is not None and r.matched is True


@pytest.mark.asyncio
async def test_merge_branches_annotates_without_git() -> None:
    ce = ContextEngine()
    ex = RailBuiltinExecutor(ce)
    job = await ce.create_goal("job", source="decomposition", priority=50)
    maker = await ce.create_goal(
        "maker auth", parent_id=job.id, source="decomposition", priority=75
    )
    await ce.complete_goal(maker.id)
    state = RailJobState(
        job_id=job.id,
        rail_id="greenfield-system",
        rail_version="1.14",
        worktrees_enabled=False,
        wave_slices=["auth", "chat"],
        spawned_slices={"auth": maker.id},
        decompose_plan=[
            {"slice": "auth", "description": "auth", "tags": ["implementation", "maker"]},
            {
                "slice": "chat",
                "description": "chat",
                "tags": ["implementation", "maker"],
                "depends_on": ["auth"],
            },
        ],
    )
    await ex.bind_job(state)
    await ex.annotate_goal(
        maker.id,
        job.id,
        tags=["implementation", "maker", "auth", "slice:auth"],
        role="maker",
        branch_id="job/test/auth",
        branch_status="active",
    )
    result = await ex.invoke("merge_branches", job_id=job.id, trigger_goal_id=maker.id)
    assert result.status == "success"
    st = await ex.job_state(job.id)
    assert st is not None
    assert st.annotations[maker.id].branch_status == "merged"
    # chat should spawn after merge/spawn-ready
    assert "chat" in st.spawned_slices
    assert any("review" in (st.annotations[g].tags or []) for g in result.created_goal_ids)
