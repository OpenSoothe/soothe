"""Tests for job/slice worktree recycling on merge and job completion."""

from __future__ import annotations

import subprocess
from pathlib import Path

from soothe.autopilot.rails import worktree_ops


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
    cur = _git(repo, "branch", "--show-current").stdout.strip()
    if cur != "master":
        _git(repo, "branch", "-M", "master")
    return repo


def _make_slice_worktree(repo: Path, slug: str, job_id: str = "50c750ae") -> Path:
    """Create a slice worktree under repo/.soothe/worktrees/{slug}."""
    wt = repo / ".soothe" / "worktrees" / slug
    branch = f"job/{job_id[:8]}/{slug}"
    worktree_ops.ensure_worktree(repo, branch=branch, worktree_path=wt, start_point="master")
    (wt / f"{slug}.txt").write_text("slice\n", encoding="utf-8")
    _git(wt, "add", "-A")
    _git(wt, "-c", "user.email= rail@soothe.local", "-c", "user.name=Test", "commit", "-m", "slice")
    return wt


def test_remove_worktree_removes_linked_worktree_and_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    wt = _make_slice_worktree(repo, "slice-a")
    assert wt.is_dir()

    result = worktree_ops.remove_worktree(repo, wt)

    assert result.ok
    assert not wt.exists()
    # Branch deleted (rev-parse --verify returns non-zero when ref is gone).
    branch_check = subprocess.run(
        ["git", "rev-parse", "--verify", "job/50c750ae/slice-a"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert branch_check.returncode != 0


def test_remove_worktree_rejects_path_outside_worktrees_dir(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    # The primary repo dir is NOT under .soothe/worktrees/ — must refuse.
    result = worktree_ops.remove_worktree(repo, repo)
    assert not result.ok
    assert "refuse" in result.detail.lower()
    assert repo.is_dir()  # untouched


def test_remove_worktree_missing_path_is_ok(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    missing = repo / ".soothe" / "worktrees" / "nope"
    result = worktree_ops.remove_worktree(repo, missing)
    assert result.ok


def test_remove_worktree_only_works_under_soothe_worktrees(tmp_path: Path) -> None:
    """A path that exists but is not under .soothe/worktrees/ is refused."""
    repo = _init_repo(tmp_path)
    bogus = repo / "elsewhere"
    bogus.mkdir()
    result = worktree_ops.remove_worktree(repo, bogus)
    assert not result.ok
    assert bogus.is_dir()


def test_recycle_job_worktrees_removes_merged_for_job(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    wt = _make_slice_worktree(repo, "slice-x", job_id="50c750ae")
    # Merge the slice branch into master so recycle considers it.
    _git(repo, "merge", "--no-edit", "job/50c750ae/slice-x")

    removed = worktree_ops.recycle_job_worktrees(repo, job_id="50c750ae")

    assert removed == 1
    assert not wt.exists()


def test_recycle_job_worktrees_leaves_unrelated_worktrees(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    wt_a = _make_slice_worktree(repo, "slice-a", job_id="50c750ae")
    wt_b = _make_slice_worktree(repo, "slice-b", job_id="60c750ae")
    _git(repo, "merge", "--no-edit", "job/50c750ae/slice-a")

    removed = worktree_ops.recycle_job_worktrees(repo, job_id="50c750ae")

    assert removed == 1
    assert not wt_a.exists()
    # Unrelated job's worktree untouched.
    assert wt_b.is_dir()


def test_recycle_job_worktrees_empty_dir_is_noop(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    assert worktree_ops.recycle_job_worktrees(repo, job_id="50c750ae") == 0
