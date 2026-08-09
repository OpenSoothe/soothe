"""Unit tests for resilient host merge + resolve escalation (IG-732 P4)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from soothe.autopilot.rail import worktree_ops
from soothe.autopilot.rail.builtins_exec import RailBuiltinExecutor, RailJobState
from soothe.autopilot.rail.guards import _structural_short_circuit
from soothe.context import ContextEngine


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")
    # Ensure master exists (git may use main).
    cur = _git(repo, "branch", "--show-current").stdout.strip()
    if cur != "master":
        _git(repo, "branch", "-M", "master")
    return repo


def test_merge_succeeds_with_dirty_primary(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "job/test/_base")
    _git(repo, "checkout", "-b", "job/test/slice-a")
    (repo / "slice_a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "slice_a.txt")
    _git(repo, "commit", "-m", "slice a")
    _git(repo, "checkout", "master")
    # Dirty primary must not block merge into job branch.
    (repo / "README.md").write_text("dirty primary\n", encoding="utf-8")

    result = worktree_ops.merge_branch_into(
        repo,
        target_branch="job/test/_base",
        source_branch="job/test/slice-a",
        base_branch="master",
    )
    assert result.ok is True
    assert result.conflict is False
    files = _git(repo, "ls-tree", "-r", "--name-only", "job/test/_base").stdout
    assert "slice_a.txt" in files
    # Primary still dirty / not forced onto job branch.
    assert (repo / "README.md").read_text(encoding="utf-8") == "dirty primary\n"


def test_merge_conflict_sets_conflict_flag(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "job/test/_base")
    (repo / "clash.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "clash.txt")
    _git(repo, "commit", "-m", "base clash")
    _git(repo, "checkout", "-b", "job/test/slice-b")
    (repo / "clash.txt").write_text("slice\n", encoding="utf-8")
    _git(repo, "add", "clash.txt")
    _git(repo, "commit", "-m", "slice clash")
    _git(repo, "checkout", "job/test/_base")
    (repo / "clash.txt").write_text("other\n", encoding="utf-8")
    _git(repo, "add", "clash.txt")
    _git(repo, "commit", "-m", "base other")

    result = worktree_ops.merge_branch_into(
        repo,
        target_branch="job/test/_base",
        source_branch="job/test/slice-b",
        base_branch="master",
    )
    assert result.ok is False
    assert result.conflict is True
    assert result.needs_agent is True


def test_dirty_worktree_materialize_then_merge(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "branch", "job/test/_base", "master")
    wt = repo / ".soothe" / "worktrees" / "slice-c"
    wt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", "job/test/slice-c", str(wt), "master"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    (wt / "slice_c.txt").write_text("c\n", encoding="utf-8")

    result = worktree_ops.merge_branch_into(
        repo,
        target_branch="job/test/_base",
        source_branch="job/test/slice-c",
        maker_worktree=wt,
        base_branch="master",
    )
    assert result.ok is True, result.detail
    files = _git(repo, "ls-tree", "-r", "--name-only", "job/test/_base").stdout
    assert "slice_c.txt" in files


def test_orphan_source_escalates_needs_agent(tmp_path: Path) -> None:
    """Orphan tips are unrelated history — host escalates (no complex merge)."""
    repo = _init_repo(tmp_path)
    _git(repo, "branch", "job/test/_base", "master")
    wt = repo / ".soothe" / "worktrees" / "orphan"
    wt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(wt), "master"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "checkout", "--orphan", "job/test/orphan"],
        cwd=wt,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "rm", "-rf", "."], cwd=wt, check=False, capture_output=True)
    (wt / "orphan.txt").write_text("o\n", encoding="utf-8")

    result = worktree_ops.merge_branch_into(
        repo,
        target_branch="job/test/_base",
        source_branch="job/test/orphan",
        maker_worktree=wt,
        base_branch="master",
    )
    assert result.ok is False
    assert result.needs_agent is True


def test_maker_needs_merge_idle_and_resolve_guards() -> None:
    idle = _structural_short_circuit(
        condition_name="maker_needs_merge",
        event="dag_idle",
        trigger_tags=[],
        structural={
            "unmerged_maker_ids": ["m1"],
            "resolve_inflight_blocks_all": False,
        },
    )
    assert idle is not None and idle.matched is True

    blocked = _structural_short_circuit(
        condition_name="maker_needs_merge",
        event="dag_idle",
        trigger_tags=[],
        structural={
            "unmerged_maker_ids": ["m1"],
            "resolve_inflight_blocks_all": True,
        },
    )
    assert blocked is not None and blocked.matched is False

    resolve_retry = _structural_short_circuit(
        condition_name="maker_needs_merge",
        event="goal_completed",
        trigger_tags=["resolve", "merge", "implementation"],
        structural={
            "trigger_is_merge_resolve": True,
            "unmerged_maker_ids": ["m1"],
        },
    )
    assert resolve_retry is not None and resolve_retry.matched is True

    done = _structural_short_circuit(
        condition_name="maker_needs_merge",
        event="dag_idle",
        trigger_tags=[],
        structural={"unmerged_maker_ids": []},
    )
    assert done is not None and done.matched is False


@pytest.mark.asyncio
async def test_merge_branches_spawns_resolve_on_needs_agent(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    ce = ContextEngine()
    ex = RailBuiltinExecutor(ce)
    job = await ce.create_goal("job", source="decomposition", priority=50, workspace=str(repo))
    maker = await ce.create_goal(
        "maker slice",
        parent_id=job.id,
        source="decomposition",
        priority=75,
        workspace=str(repo),
    )
    await ce.complete_goal(maker.id)
    state = RailJobState(
        job_id=job.id,
        rail_id="greenfield-system",
        rail_version="1.14",
        worktrees_enabled=True,
        job_branch="job/test/_base",
        base_branch="master",
        wave_slices=["slice"],
        spawned_slices={"slice": maker.id},
        decompose_plan=[
            {"slice": "slice", "description": "s", "tags": ["implementation", "maker"]},
        ],
    )
    await ex.bind_job(state)
    # Point maker at a missing source branch → needs_agent → resolve goal.
    await ex.annotate_goal(
        maker.id,
        job.id,
        tags=["implementation", "maker", "slice", "slice:slice"],
        role="maker",
        branch_id="job/test/missing-slice",
        branch_status="active",
    )
    result = await ex.invoke("merge_branches", job_id=job.id, trigger_goal_id=maker.id)
    assert result.status == "success"
    assert result.created_goal_ids
    st = await ex.job_state(job.id)
    assert st is not None
    assert st.annotations[maker.id].branch_status == "conflict"
    resolve_id = result.created_goal_ids[0]
    assert "resolve" in (st.annotations[resolve_id].tags or [])
    assert "merge" in (st.annotations[resolve_id].tags or [])


@pytest.mark.asyncio
async def test_merge_branches_happy_path_marks_merged(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "branch", "job/test/_base", "master")
    _git(repo, "checkout", "-b", "job/test/slice-ok")
    (repo / "ok.txt").write_text("ok\n", encoding="utf-8")
    _git(repo, "add", "ok.txt")
    _git(repo, "commit", "-m", "ok")
    _git(repo, "checkout", "master")

    ce = ContextEngine()
    ex = RailBuiltinExecutor(ce)
    job = await ce.create_goal("job", source="decomposition", priority=50, workspace=str(repo))
    maker = await ce.create_goal(
        "maker ok",
        parent_id=job.id,
        source="decomposition",
        priority=75,
        workspace=str(repo),
    )
    await ce.complete_goal(maker.id)
    state = RailJobState(
        job_id=job.id,
        rail_id="greenfield-system",
        rail_version="1.14",
        worktrees_enabled=True,
        job_branch="job/test/_base",
        base_branch="master",
        wave_slices=["ok"],
        spawned_slices={"ok": maker.id},
        decompose_plan=[
            {"slice": "ok", "description": "ok", "tags": ["implementation", "maker"]},
        ],
    )
    await ex.bind_job(state)
    await ex.annotate_goal(
        maker.id,
        job.id,
        tags=["implementation", "maker", "ok", "slice:ok"],
        role="maker",
        branch_id="job/test/slice-ok",
        branch_status="active",
    )
    result = await ex.invoke("merge_branches", job_id=job.id, trigger_goal_id=maker.id)
    assert result.status == "success", result.detail
    st = await ex.job_state(job.id)
    assert st is not None
    assert st.annotations[maker.id].branch_status == "merged"
    files = _git(repo, "ls-tree", "-r", "--name-only", "job/test/_base").stdout
    assert "ok.txt" in files


def test_greenfield_has_dag_idle_merge_rule() -> None:
    from soothe.rails import LoopRailCatalog

    rail = LoopRailCatalog().resolve("greenfield-system")
    idle_merge = [
        e
        for e in rail.flow
        if e.get("event") == "dag_idle" and e.get("when") == "maker_needs_merge"
    ]
    assert idle_merge
    assert idle_merge[0].get("then") == "merge_branches"
