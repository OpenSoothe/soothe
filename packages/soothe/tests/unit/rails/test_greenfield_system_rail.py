"""Unit tests for greenfield-system rail + CE builtins (IG-687)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from soothe.autopilot.rail.builtins_exec import RailBuiltinExecutor, RailJobState
from soothe.autopilot.rail.guards import GuardResult, _structural_short_circuit
from soothe.context import ContextEngine
from soothe.rails import LoopRailCatalog


def test_greenfield_system_rail_loads() -> None:
    rail = LoopRailCatalog().resolve("greenfield-system")
    assert rail.id == "greenfield-system"
    thens = [str(e.get("then")) for e in rail.flow]
    assert thens[0] == "plan_milestones"
    assert "spawn_wave_makers" in thens
    assert "spawn_integrate" in thens
    assert "commit_milestone" in thens
    assert "review" in thens


def test_architecture_ready_short_circuit() -> None:
    structural = {
        "architecture_goal_ids": ["a1"],
        "all_architecture_terminal": True,
        "implementation_goal_ids": [],
        "pending_or_active_count": 0,
    }
    r = _structural_short_circuit(
        condition_name="architecture_ready",
        event="goal_completed",
        trigger_tags=["architecture", "planning"],
        structural=structural,
    )
    assert isinstance(r, GuardResult)
    assert r.matched is True


def test_needs_commit_only_on_integrate() -> None:
    r = _structural_short_circuit(
        condition_name="needs_commit",
        event="goal_completed",
        trigger_tags=["implementation"],
        structural={"pending_or_active_count": 0},
    )
    assert r is not None and r.matched is False
    r2 = _structural_short_circuit(
        condition_name="needs_commit",
        event="goal_completed",
        trigger_tags=["integrate"],
        structural={"pending_or_active_count": 0},
    )
    assert r2 is not None and r2.matched is True


@pytest.mark.asyncio
async def test_plan_milestones_wires_root_depends_on(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Build system", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce)
    await ex.bind_job(RailJobState(job_id=root.id, rail_id="greenfield-system", rail_version="1.0"))
    result = await ex.invoke("plan_milestones", job_id=root.id)
    assert result.status == "success"
    assert len(result.created_goal_ids) == 1
    arch_id = result.created_goal_ids[0]
    arch = await ce.get_goal(arch_id)
    assert arch is not None
    assert "architecture" in (arch.rail_tags or [])
    refreshed = await ce.get_goal(root.id)
    assert refreshed is not None
    assert arch_id in refreshed.depends_on
    assert arch_id not in (arch.depends_on or [])


@pytest.mark.asyncio
async def test_spawn_wave_makers_worktrees_and_no_root_dep(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    ce = ContextEngine()
    root = await ce.create_goal("Build system", workspace=str(repo), priority=70)
    ex = RailBuiltinExecutor(ce)
    state = RailJobState(
        job_id=root.id,
        rail_id="greenfield-system",
        rail_version="1.0",
        wave_modules=["frontend", "backend"],
        worktrees_enabled=True,
    )
    await ex.bind_job(state)

    arch = await ce.create_goal(
        "Architecture",
        parent_id=root.id,
        source="decomposition",
        rail_id="greenfield-system",
    )
    await ce.complete_goal(arch.id)
    await ex.annotate_goal(arch.id, root.id, tags=["architecture", "planning"], role="planner")

    result = await ex.invoke("spawn_wave_makers", job_id=root.id, trigger_goal_id=arch.id)
    assert result.status == "success"
    assert len(result.created_goal_ids) == 2
    for gid in result.created_goal_ids:
        g = await ce.get_goal(gid)
        assert g is not None
        assert root.id not in (g.depends_on or [])
        assert arch.id in (g.depends_on or [])
        assert g.role == "maker"
        assert g.workspace is not None
        assert "worktrees" in g.workspace
        assert Path(g.workspace).is_dir()

    refreshed = await ce.get_goal(root.id)
    assert refreshed is not None
    for gid in result.created_goal_ids:
        assert gid in refreshed.depends_on


@pytest.mark.asyncio
async def test_integrate_commit_review_chain() -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Build system", priority=70)
    ex = RailBuiltinExecutor(ce)
    await ex.bind_job(
        RailJobState(
            job_id=root.id,
            rail_id="greenfield-system",
            rail_version="1.0",
            wave_modules=["a"],
            worktrees_enabled=False,
        )
    )
    # Pretend wave 1 makers already done
    state = await ex.job_state(root.id)
    assert state is not None
    state.wave_index = 1
    maker = await ce.create_goal(
        "Maker a",
        parent_id=root.id,
        source="decomposition",
        rail_id="greenfield-system",
    )
    await ce.complete_goal(maker.id)
    await ex.annotate_goal(
        maker.id, root.id, tags=["implementation", "maker", "wave-1", "a"], role="maker"
    )

    integ = await ex.invoke("spawn_integrate", job_id=root.id, trigger_goal_id=maker.id)
    assert integ.status == "success"
    integ_id = integ.created_goal_ids[0]
    await ce.complete_goal(integ_id)

    commit = await ex.invoke("commit_milestone", job_id=root.id, trigger_goal_id=integ_id)
    assert commit.status == "success"
    commit_id = commit.created_goal_ids[0]
    cg = await ce.get_goal(commit_id)
    assert cg is not None
    assert "commit" in (cg.rail_tags or [])
    assert integ_id in (cg.depends_on or [])
    await ce.complete_goal(commit_id)

    rev = await ex.invoke("review", job_id=root.id, trigger_goal_id=commit_id)
    assert rev.status == "success"
    rg = await ce.get_goal(rev.created_goal_ids[0])
    assert rg is not None
    assert commit_id in (rg.depends_on or [])
    assert "Diff-scoped" in rg.description
