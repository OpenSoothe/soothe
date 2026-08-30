"""Host git helpers for job-branch merge / worktree refresh / land."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_MERGE_WORKTREE_REL = Path(".soothe") / "merge" / "_host"


@dataclass(frozen=True)
class GitOpResult:
    """Outcome of a host git operation."""

    ok: bool
    detail: str = ""
    conflict: bool = False
    needs_agent: bool = False


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _ref_exists(repo: Path, ref: str) -> bool:
    proc = _run_git(repo, "rev-parse", "--verify", ref)
    return proc.returncode == 0


def detect_base_branch(repo: Path) -> str:
    """Return `main` or `master` (prefer main) when present."""
    for name in ("main", "master"):
        if _ref_exists(repo, f"refs/heads/{name}"):
            return name
    # Detached / empty — fall back to current branch name.
    proc = _run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    name = (proc.stdout or "").strip()
    if name and name != "HEAD":
        return name
    return "master"


def ensure_job_branch(repo: Path, *, job_branch: str, base_branch: str) -> GitOpResult:
    """Create `job_branch` from the richest safe tip when missing."""
    if _ref_exists(repo, f"refs/heads/{job_branch}"):
        return GitOpResult(ok=True, detail=f"job branch exists: {job_branch}")

    # Prefer primary HEAD when it is a descendant of base (or base missing).
    start = base_branch if _ref_exists(repo, f"refs/heads/{base_branch}") else None
    head = _run_git(repo, "rev-parse", "--verify", "HEAD")
    if head.returncode == 0:
        head_sha = (head.stdout or "").strip()
        if start is None:
            start = head_sha
        else:
            contains = _run_git(repo, "merge-base", "--is-ancestor", start, "HEAD")
            if contains.returncode == 0:
                start = head_sha

    if start is None:
        proc = _run_git(repo, "branch", job_branch)
        start_label = "HEAD"
    else:
        proc = _run_git(repo, "branch", job_branch, start)
        head_sha = (head.stdout or "").strip() if head.returncode == 0 else ""
        start_label = "HEAD" if start == head_sha else start

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:300]
        return GitOpResult(
            ok=False,
            needs_agent=True,
            detail=f"create job branch failed: {err}",
        )
    return GitOpResult(ok=True, detail=f"created {job_branch} from {start_label}")


def ensure_worktree(
    repo: Path,
    *,
    branch: str,
    worktree_path: Path,
    start_point: str | None = None,
) -> Path | None:
    """Create `branch` checked out at `worktree_path` from `start_point`."""
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


def ensure_source_branch_tip(
    repo: Path,
    *,
    source_branch: str,
    maker_worktree: Path | None,
) -> GitOpResult:
    """Best-effort single materialize commit when source tip is missing or WT dirty.

    Complex failures escalate with `needs_agent=True` (no multi-step recovery).
    """
    tip_ok = _ref_exists(repo, f"refs/heads/{source_branch}")
    if maker_worktree is None or not maker_worktree.exists():
        if tip_ok:
            return GitOpResult(ok=True, detail=f"source tip exists: {source_branch}")
        return GitOpResult(
            ok=False,
            needs_agent=True,
            detail=(
                f"source branch {source_branch} has no tip and maker worktree "
                "is unavailable for materialize"
            ),
        )

    status = _run_git(maker_worktree, "status", "--porcelain")
    dirty = bool((status.stdout or "").strip())
    if tip_ok and not dirty:
        return GitOpResult(ok=True, detail=f"source tip clean: {source_branch}")

    # Ensure we are on the maker branch inside the worktree when possible.
    cur = _run_git(maker_worktree, "rev-parse", "--abbrev-ref", "HEAD")
    cur_name = (cur.stdout or "").strip()
    if cur_name != source_branch:
        # Unborn / wrong branch: try checkout -B onto source from current tree.
        co = _run_git(maker_worktree, "checkout", "-B", source_branch)
        if co.returncode != 0 and not tip_ok:
            err = (co.stderr or co.stdout or "").strip()[:300]
            return GitOpResult(
                ok=False,
                needs_agent=True,
                detail=f"cannot checkout source branch {source_branch}: {err}",
            )

    add = _run_git(maker_worktree, "add", "-A")
    if add.returncode != 0:
        err = (add.stderr or add.stdout or "").strip()[:300]
        return GitOpResult(
            ok=False,
            needs_agent=True,
            detail=f"materialize add failed: {err}",
        )
    commit = _run_git(
        maker_worktree,
        "-c",
        "user.email=rail@soothe.local",
        "-c",
        "user.name=Soothe Rail",
        "commit",
        "-m",
        "rail: materialize slice for host merge",
    )
    if commit.returncode != 0:
        err = (commit.stderr or commit.stdout or "").strip()[:300]
        if tip_ok and "nothing to commit" in err.lower():
            return GitOpResult(ok=True, detail=f"source tip exists: {source_branch}")
        return GitOpResult(
            ok=False,
            needs_agent=True,
            detail=f"materialize commit failed: {err}",
        )
    if not _ref_exists(repo, f"refs/heads/{source_branch}"):
        return GitOpResult(
            ok=False,
            needs_agent=True,
            detail=f"source branch {source_branch} still has no tip after materialize",
        )
    return GitOpResult(ok=True, detail=f"materialized tip on {source_branch}")


def _ensure_merge_worktree(repo: Path, *, target_branch: str) -> GitOpResult:
    """Return a clean worktree checked out to `target_branch` (never primary)."""
    merge_wt = repo / _MERGE_WORKTREE_REL
    merge_wt.parent.mkdir(parents=True, exist_ok=True)

    if merge_wt.exists():
        # Reset hard to target tip; keep worktree attached.
        co = _run_git(merge_wt, "checkout", "-f", target_branch)
        if co.returncode != 0:
            # Re-add if worktree metadata is broken.
            _run_git(repo, "worktree", "remove", "--force", str(merge_wt))
        else:
            _run_git(merge_wt, "reset", "--hard", "HEAD")
            _run_git(merge_wt, "clean", "-fd")
            return GitOpResult(ok=True, detail=str(merge_wt))

    if not merge_wt.exists():
        proc = _run_git(
            repo,
            "worktree",
            "add",
            "--force",
            str(merge_wt),
            target_branch,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[:300]
            return GitOpResult(
                ok=False,
                needs_agent=True,
                detail=f"merge worktree add failed: {err}",
            )
    _run_git(merge_wt, "reset", "--hard", "HEAD")
    _run_git(merge_wt, "clean", "-fd")
    return GitOpResult(ok=True, detail=str(merge_wt))


def merge_branch_into(
    repo: Path,
    *,
    target_branch: str,
    source_branch: str,
    maker_worktree: Path | str | None = None,
    base_branch: str | None = None,
) -> GitOpResult:
    """Happy-path merge `source_branch` into `target_branch` via isolated merge WT.

    Never checks out `target_branch` in the dirty primary workspace. Complex
    failures set `needs_agent=True` or `conflict=True` for StrangeLoop resolve.
    """
    base = base_branch or detect_base_branch(repo)
    ensured = ensure_job_branch(repo, job_branch=target_branch, base_branch=base)
    if not ensured.ok:
        return GitOpResult(
            ok=False,
            needs_agent=True,
            detail=ensured.detail,
        )

    wt_path: Path | None = None
    if maker_worktree is not None:
        wt_path = Path(maker_worktree)
    tip = ensure_source_branch_tip(repo, source_branch=source_branch, maker_worktree=wt_path)
    if not tip.ok:
        return tip

    merge_wt_res = _ensure_merge_worktree(repo, target_branch=target_branch)
    if not merge_wt_res.ok:
        return merge_wt_res
    merge_wt = Path(merge_wt_res.detail)

    merge = _run_git(merge_wt, "merge", "--no-edit", source_branch)
    out = ((merge.stdout or "") + (merge.stderr or "")).strip()
    if merge.returncode != 0:
        conflict = "CONFLICT" in out or _run_git(merge_wt, "ls-files", "-u").stdout.strip() != ""
        if conflict:
            _run_git(merge_wt, "merge", "--abort")
            return GitOpResult(
                ok=False,
                conflict=True,
                needs_agent=True,
                detail=f"merge conflict merging {source_branch} into {target_branch}",
            )
        _run_git(merge_wt, "merge", "--abort")
        return GitOpResult(
            ok=False,
            needs_agent=True,
            detail=f"merge failed: {out[:300]}",
        )
    return GitOpResult(ok=True, detail=f"merged {source_branch} into {target_branch}")


def refresh_worktree_onto(
    worktree: Path,
    *,
    onto_branch: str,
) -> GitOpResult:
    """Rebase current worktree branch onto `onto_branch`."""
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
                needs_agent=True,
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
    """Merge `job_branch` into `base_branch` (final land)."""
    return merge_branch_into(
        repo,
        target_branch=base_branch,
        source_branch=job_branch,
        base_branch=base_branch,
    )


_WORKTREES_REL = Path(".soothe") / "worktrees"


def _worktree_branch_for(repo: Path, worktree_path: Path) -> str | None:
    """Best-effort branch name checked out in `worktree_path`."""
    cur = _run_git(worktree_path, "rev-parse", "--abbrev-ref", "HEAD")
    name = (cur.stdout or "").strip()
    if name and name != "HEAD" and _ref_exists(repo, f"refs/heads/{name}"):
        return name
    return None


def remove_worktree(repo: Path, worktree_path: Path) -> GitOpResult:
    """Remove a job/slice worktree and its branch (best-effort, force).

    Only operates on paths under `repo/.soothe/worktrees/` — rejects
    anything else so the primary workspace or arbitrary dirs are never
    touched. Force-removes the linked worktree, then best-effort deletes
    its slice branch (merged branches delete cleanly; unmerged force-delete
    is safe because the caller only invokes this after a merge or on cancel).
    Never raises; returns a `GitOpResult`.
    """
    try:
        rel = worktree_path.relative_to((repo / _WORKTREES_REL).resolve())
    except (ValueError, OSError) as exc:
        return GitOpResult(
            ok=False,
            detail=(
                f"refuse remove_worktree: {worktree_path} not under {repo / _WORKTREES_REL} ({exc})"
            ),
        )
    if not worktree_path.exists() and not (repo / _WORKTREES_REL / rel).exists():
        return GitOpResult(ok=True, detail=f"worktree absent: {worktree_path}")

    branch = _worktree_branch_for(repo, worktree_path)
    rm = _run_git(repo, "worktree", "remove", "--force", str(worktree_path))
    if rm.returncode != 0:
        # Prune broken metadata as a last resort.
        _run_git(repo, "worktree", "prune")
        if worktree_path.exists():
            return GitOpResult(
                ok=False,
                needs_agent=True,
                detail=(f"worktree remove failed: {(rm.stderr or rm.stdout or '').strip()[:300]}"),
            )

    if branch:
        del_branch = _run_git(repo, "branch", "-D", branch)
        if del_branch.returncode != 0:
            return GitOpResult(
                ok=True,
                detail=(
                    f"removed worktree {worktree_path.name}; branch {branch} "
                    f"kept: {(del_branch.stderr or del_branch.stdout or '').strip()[:200]}"
                ),
            )
    return GitOpResult(ok=True, detail=f"removed worktree {worktree_path.name}")


def recycle_job_worktrees(repo: Path, *, job_id: str) -> int:
    """Sweep all worktrees under `repo/.soothe/worktrees/` for `job_id`.

    Removes slice worktrees whose branch is merged into the base branch and
    any leftover job worktree dirs after the job lands. Best-effort: logs
    each removal, never raises. Returns the count removed.
    """
    base = detect_base_branch(repo)
    wt_root = repo / _WORKTREES_REL
    if not wt_root.is_dir():
        return 0
    removed = 0
    for entry in sorted(wt_root.iterdir()):
        if not entry.is_dir():
            continue
        # Only touch worktrees whose name or branch references this job.
        branch = _worktree_branch_for(repo, entry)
        owns_job = job_id[:8] in (entry.name + " " + (branch or ""))
        if not owns_job and branch is None:
            continue
        merged = (
            branch is not None
            and _run_git(repo, "merge-base", "--is-ancestor", branch, base).returncode == 0
        )
        if not merged and not owns_job:
            continue
        result = remove_worktree(repo, entry)
        if result.ok:
            removed += 1
            logger.info("recycle_job_worktrees: %s (job=%s)", result.detail, job_id[:8])
        else:
            logger.warning(
                "recycle_job_worktrees: %s kept (job=%s)",
                result.detail,
                job_id[:8],
            )
    return removed
