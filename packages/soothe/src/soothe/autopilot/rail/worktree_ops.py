"""Host git helpers for job-branch merge / worktree refresh / land (IG-732)."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GitOpResult:
    """Outcome of a host git operation."""

    ok: bool
    detail: str = ""
    conflict: bool = False


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def detect_base_branch(repo: Path) -> str:
    """Return ``main`` or ``master`` (prefer main) when present."""
    for name in ("main", "master"):
        proc = _run_git(repo, "rev-parse", "--verify", f"refs/heads/{name}")
        if proc.returncode == 0:
            return name
    # Detached / empty — fall back to current branch name.
    proc = _run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    name = (proc.stdout or "").strip()
    if name and name != "HEAD":
        return name
    return "master"


def ensure_job_branch(repo: Path, *, job_branch: str, base_branch: str) -> GitOpResult:
    """Create ``job_branch`` from ``base_branch`` when missing."""
    exists = _run_git(repo, "rev-parse", "--verify", f"refs/heads/{job_branch}")
    if exists.returncode == 0:
        return GitOpResult(ok=True, detail=f"job branch exists: {job_branch}")
    base_ok = _run_git(repo, "rev-parse", "--verify", f"refs/heads/{base_branch}")
    if base_ok.returncode != 0:
        # Create from HEAD if base missing.
        proc = _run_git(repo, "branch", job_branch)
    else:
        proc = _run_git(repo, "branch", job_branch, base_branch)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:300]
        return GitOpResult(ok=False, detail=f"create job branch failed: {err}")
    return GitOpResult(ok=True, detail=f"created {job_branch} from {base_branch}")


def ensure_worktree(
    repo: Path,
    *,
    branch: str,
    worktree_path: Path,
    start_point: str | None = None,
) -> Path | None:
    """Create ``branch`` checked out at ``worktree_path`` from ``start_point``."""
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    if worktree_path.exists():
        return worktree_path
    start = start_point or "HEAD"
    if start != "HEAD":
        check = _run_git(repo, "rev-parse", "--verify", start)
        if check.returncode != 0:
            start = "HEAD"
    try:
        proc = _run_git(
            repo,
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
            start,
        )
        if proc.returncode != 0:
            # Branch may already exist; attach worktree to it from HEAD tip.
            proc = _run_git(repo, "worktree", "add", str(worktree_path), branch)
            if proc.returncode != 0:
                proc = _run_git(
                    repo,
                    "worktree",
                    "add",
                    "-b",
                    branch,
                    str(worktree_path),
                    "HEAD",
                )
        if proc.returncode != 0:
            logger.warning(
                "git worktree add failed for %s: %s",
                worktree_path,
                (proc.stderr or proc.stdout or "").strip()[:300],
            )
            return None
        return worktree_path
    except OSError as exc:
        logger.warning("git worktree unavailable: %s", exc)
        return None


def merge_branch_into(
    repo: Path,
    *,
    target_branch: str,
    source_branch: str,
) -> GitOpResult:
    """Merge ``source_branch`` into ``target_branch`` in ``repo`` (no commit message editor)."""
    checkout = _run_git(repo, "checkout", target_branch)
    if checkout.returncode != 0:
        err = (checkout.stderr or checkout.stdout or "").strip()[:300]
        return GitOpResult(ok=False, detail=f"checkout {target_branch} failed: {err}")

    merge = _run_git(repo, "merge", "--no-edit", source_branch)
    out = ((merge.stdout or "") + (merge.stderr or "")).strip()
    if merge.returncode != 0:
        conflict = "CONFLICT" in out or _run_git(repo, "ls-files", "-u").stdout.strip() != ""
        if conflict:
            _run_git(repo, "merge", "--abort")
            return GitOpResult(
                ok=False,
                conflict=True,
                detail=f"merge conflict merging {source_branch} into {target_branch}",
            )
        return GitOpResult(ok=False, detail=f"merge failed: {out[:300]}")
    return GitOpResult(ok=True, detail=f"merged {source_branch} into {target_branch}")


def refresh_worktree_onto(
    worktree: Path,
    *,
    onto_branch: str,
) -> GitOpResult:
    """Rebase current worktree branch onto ``onto_branch``."""
    if not worktree.exists():
        return GitOpResult(ok=False, detail=f"worktree missing: {worktree}")
    fetch = _run_git(worktree, "fetch", "origin", onto_branch)
    del fetch  # local-only repos may fail; ignore
    rebase = _run_git(worktree, "rebase", onto_branch)
    if rebase.returncode != 0:
        # Try merge as fallback when rebase fails on dirty/divergent trees.
        _run_git(worktree, "rebase", "--abort")
        merge = _run_git(worktree, "merge", "--no-edit", onto_branch)
        if merge.returncode != 0:
            out = (merge.stderr or merge.stdout or "").strip()[:300]
            conflict = "CONFLICT" in out
            if conflict:
                _run_git(worktree, "merge", "--abort")
            return GitOpResult(
                ok=False,
                conflict=conflict,
                detail=f"refresh failed for {worktree.name}: {out}",
            )
        return GitOpResult(ok=True, detail=f"merged {onto_branch} into {worktree.name}")
    return GitOpResult(ok=True, detail=f"rebased {worktree.name} onto {onto_branch}")


def land_job_branch(
    repo: Path,
    *,
    job_branch: str,
    base_branch: str,
) -> GitOpResult:
    """Merge ``job_branch`` into ``base_branch`` (final land)."""
    return merge_branch_into(repo, target_branch=base_branch, source_branch=job_branch)
