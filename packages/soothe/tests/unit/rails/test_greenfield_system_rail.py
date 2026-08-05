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
    assert "spawn_feedback_cycle" in thens


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


def test_needs_review_architecture_requires_commit() -> None:
    """Greenfield: maker complete must not fire review before commit gate."""
    arch_structural = {
        "architecture_goal_ids": ["a1"],
        "commit_goal_ids": [],
        "pending_or_active_count": 0,
    }
    maker = _structural_short_circuit(
        condition_name="needs_review",
        event="goal_completed",
        trigger_tags=["implementation", "maker"],
        structural=arch_structural,
    )
    assert maker is not None and maker.matched is False

    empty_commits = _structural_short_circuit(
        condition_name="needs_review",
        event="goal_completed",
        trigger_tags=["implementation"],
        structural={
            "architecture_goal_ids": ["a1"],
            "commit_goal_ids": [],
            "all_commit_terminal": True,
            "pending_or_active_count": 0,
        },
    )
    assert empty_commits is not None and empty_commits.matched is False

    after_commit = _structural_short_circuit(
        condition_name="needs_review",
        event="goal_completed",
        trigger_tags=["commit", "milestone"],
        structural={
            "architecture_goal_ids": ["a1"],
            "commit_goal_ids": ["c1"],
            "all_commit_terminal": True,
            "pending_or_active_count": 0,
        },
    )
    assert after_commit is not None and after_commit.matched is True


def test_needs_review_non_architecture_allows_implementation() -> None:
    r = _structural_short_circuit(
        condition_name="needs_review",
        event="goal_completed",
        trigger_tags=["implementation"],
        structural={"architecture_goal_ids": [], "pending_or_active_count": 0},
    )
    assert r is not None and r.matched is True


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


@pytest.mark.asyncio
async def test_spawn_feedback_cycle_order() -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Build system", priority=70)
    ex = RailBuiltinExecutor(ce)
    await ex.bind_job(RailJobState(job_id=root.id, rail_id="greenfield-system", rail_version="1.1"))
    qa = await ce.create_goal("QA", parent_id=root.id, source="decomposition")
    await ce.complete_goal(qa.id)
    await ex.annotate_goal(qa.id, root.id, tags=["qa"], role="qa")

    result = await ex.invoke("spawn_feedback_cycle", job_id=root.id, trigger_goal_id=qa.id)
    assert result.status == "success"
    assert len(result.created_goal_ids) == 3
    diagnose_id, optimize_id, verify_id = result.created_goal_ids
    diagnose = await ce.get_goal(diagnose_id)
    optimize = await ce.get_goal(optimize_id)
    verify = await ce.get_goal(verify_id)
    assert diagnose is not None and "diagnose" in (diagnose.rail_tags or [])
    assert optimize is not None and diagnose_id in (optimize.depends_on or [])
    assert "optimize" in (optimize.rail_tags or [])
    assert verify is not None and optimize_id in (verify.depends_on or [])
    assert "verify" in (verify.rail_tags or [])
    state = await ex.job_state(root.id)
    assert state is not None and state.feedback_round == 1

    # In-flight skip
    skip = await ex.invoke("spawn_feedback_cycle", job_id=root.id, trigger_goal_id=qa.id)
    assert skip.status == "skipped"


def test_needs_feedback_short_circuit() -> None:
    structural = {
        "architecture_goal_ids": ["a1"],
        "feedback_inflight": False,
        "feedback_round": 0,
        "max_feedback_rounds": 8,
        "acceptance_met": False,
        "pending_or_active_count": 0,
    }
    ok = _structural_short_circuit(
        condition_name="needs_feedback",
        event="goal_completed",
        trigger_tags=["qa"],
        structural=structural,
    )
    assert ok is not None and ok.matched is True

    blocked = _structural_short_circuit(
        condition_name="needs_feedback",
        event="goal_completed",
        trigger_tags=["qa"],
        structural={**structural, "acceptance_met": True},
    )
    assert blocked is not None and blocked.matched is False


def test_dag_idle_needs_feedback_without_qa_tags() -> None:
    """Idle DAG + unmet acceptance must spawn feedback even with empty qa_ids."""
    structural = {
        "architecture_goal_ids": ["a1"],
        "qa_goal_ids": [],
        "review_goal_ids": [],
        "feedback_goal_ids": [],
        "feedback_inflight": False,
        "feedback_round": 0,
        "max_feedback_rounds": 8,
        "acceptance_met": False,
        "pending_or_active_count": 0,
        "wave_below_max": True,
    }
    feedback = _structural_short_circuit(
        condition_name="needs_feedback",
        event="dag_idle",
        trigger_tags=[],
        structural=structural,
    )
    assert feedback is not None and feedback.matched is True

    complete = _structural_short_circuit(
        condition_name="job_complete",
        event="dag_idle",
        trigger_tags=[],
        structural=structural,
    )
    assert complete is not None and complete.matched is False

    latched = _structural_short_circuit(
        condition_name="job_complete",
        event="dag_idle",
        trigger_tags=[],
        structural={**structural, "acceptance_met": True},
    )
    assert latched is not None and latched.matched is True


@pytest.mark.asyncio
async def test_rail_job_root_dispatch_skipped() -> None:
    from soothe.autopilot import AutopilotService
    from soothe.config.models import AutopilotConfig
    from soothe.events.internal_bus import InternalEventBus

    class _IdleFactory:
        def create_runner(self, loop_id: str):  # noqa: ANN001
            raise AssertionError("rail job root must not dispatch")

    bus = InternalEventBus()
    ce = ContextEngine()
    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=2, max_parallel_goals=2),
        internal_bus=bus,
        runner_factory=_IdleFactory(),
    )
    root = await ce.create_goal("root job", priority=80, workspace="/tmp/ws")
    root.rail_id = "greenfield-system"
    # Skip path: returns True without claiming/dispatching
    assert await svc._try_dispatch_goal(root) is True
    refreshed = await ce.get_goal(root.id)
    assert refreshed is not None
    assert refreshed.status == "pending"


@pytest.mark.asyncio
async def test_tags_by_goal_falls_back_to_ce_rail_tags() -> None:
    """IG-691: empty RailJobState still exposes CE rail_tags for guards."""
    ce = ContextEngine()
    root = await ce.create_goal("Build system", priority=70)
    integ = await ce.create_goal(
        "Integrate wave 1",
        parent_id=root.id,
        source="decomposition",
        rail_id="greenfield-system",
    )
    integ.rail_tags = ["integrate", "wave-1"]

    ex = RailBuiltinExecutor(ce)
    # No bind — simulates lost in-memory annotations after restart
    tags = await ex.tags_by_goal(root.id)
    assert tags.get(integ.id) == ["integrate", "wave-1"]

    needs = _structural_short_circuit(
        condition_name="needs_commit",
        event="goal_completed",
        trigger_tags=tags[integ.id],
        structural={"pending_or_active_count": 0},
    )
    assert needs is not None and needs.matched is True


@pytest.mark.asyncio
async def test_bind_job_hydrates_annotations_from_ce(tmp_path: Path) -> None:
    """IG-691: rebind after empty state restores tags from GoalNode."""
    ce = ContextEngine()
    root = await ce.create_goal("Build system", priority=70, workspace=str(tmp_path))
    integ = await ce.create_goal(
        "Integrate",
        parent_id=root.id,
        source="decomposition",
        rail_id="greenfield-system",
    )
    integ.rail_tags = ["integrate", "wave-1"]
    integ.role = "integrator"

    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path / "jobs")
    await ex.bind_job(RailJobState(job_id=root.id, rail_id="greenfield-system", rail_version="1.1"))
    tags = await ex.tags_by_goal(root.id)
    assert "integrate" in tags.get(integ.id, [])
    state = await ex.job_state(root.id)
    assert state is not None
    assert "integrate" in state.annotations[integ.id].tags


@pytest.mark.asyncio
async def test_rail_state_persists_across_new_executor(tmp_path: Path) -> None:
    """IG-691: rail_state.json restores annotations after process restart."""
    jobs_root = tmp_path / "jobs"
    ce = ContextEngine()
    root = await ce.create_goal("Build system", priority=70, workspace=str(tmp_path))
    ex1 = RailBuiltinExecutor(ce, jobs_root=jobs_root)
    await ex1.bind_job(
        RailJobState(job_id=root.id, rail_id="greenfield-system", rail_version="1.1")
    )
    maker = await ce.create_goal("Maker", parent_id=root.id, source="decomposition")
    await ex1.annotate_goal(
        maker.id,
        root.id,
        tags=["implementation", "maker", "wave-1"],
        role="maker",
    )
    state1 = await ex1.job_state(root.id)
    assert state1 is not None
    state1.wave_index = 2
    await ex1._persist_job(state1)

    # Fresh executor + CE still has mirrored rail_tags
    ex2 = RailBuiltinExecutor(ce, jobs_root=jobs_root)
    await ex2.bind_job(
        RailJobState(job_id=root.id, rail_id="greenfield-system", rail_version="1.1")
    )
    state2 = await ex2.job_state(root.id)
    assert state2 is not None
    assert state2.wave_index == 2
    assert "implementation" in state2.annotations[maker.id].tags
    tags = await ex2.tags_by_goal(root.id)
    assert "maker" in tags.get(maker.id, [])


@pytest.mark.asyncio
async def test_needs_commit_via_ce_tags_after_cleared_memory(tmp_path: Path) -> None:
    """Integrate complete with CE tags only → needs_commit still matches."""
    ce = ContextEngine()
    root = await ce.create_goal("Build system", priority=70, workspace=str(tmp_path))
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path / "jobs")
    await ex.bind_job(
        RailJobState(
            job_id=root.id,
            rail_id="greenfield-system",
            rail_version="1.1",
            wave_modules=["a"],
            worktrees_enabled=False,
        )
    )
    state = await ex.job_state(root.id)
    assert state is not None
    state.wave_index = 1
    maker = await ce.create_goal("Maker a", parent_id=root.id, source="decomposition")
    await ce.complete_goal(maker.id)
    await ex.annotate_goal(
        maker.id, root.id, tags=["implementation", "maker", "wave-1"], role="maker"
    )
    integ = await ex.invoke("spawn_integrate", job_id=root.id, trigger_goal_id=maker.id)
    integ_id = integ.created_goal_ids[0]
    await ce.complete_goal(integ_id)

    # Simulate restart: drop in-memory jobs, keep CE rail_tags
    ex._jobs.clear()
    tags = await ex.tags_by_goal(root.id)
    assert "integrate" in tags.get(integ_id, [])
    needs = _structural_short_circuit(
        condition_name="needs_commit",
        event="goal_completed",
        trigger_tags=tags[integ_id],
        structural={"pending_or_active_count": 0},
    )
    assert needs is not None and needs.matched is True
