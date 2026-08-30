"""Job-scoped GOAL.md contract artifact under `data/jobs/{job_id}/`.

Persists the Autopilot root job description as a durable filesystem snapshot
alongside rail soft-state. Distinct from workspace `GOAL.md` (operator
contract in the project tree).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

GOAL_MD_FILENAME = "GOAL.md"


def _sanitize_job_id(job_id: str) -> str:
    """Reject job_ids that would escape the jobs root."""
    if not job_id or not job_id.strip():
        raise ValueError("job_id must be a non-empty string")
    if "/" in job_id or "\\" in job_id or ".." in job_id:
        raise ValueError(f"job_id contains invalid path characters: {job_id!r}")
    return job_id


def resolve_job_goal_md_path(*, jobs_root: Path, job_id: str) -> Path:
    """Absolute path for `jobs/{job_id}/GOAL.md` under `jobs_root`."""
    root = jobs_root.expanduser().resolve()
    safe = _sanitize_job_id(job_id)
    path = (root / safe / GOAL_MD_FILENAME).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"GOAL.md path escapes jobs_root: {path}") from exc
    return path


def write_job_goal_md(
    *,
    jobs_root: Path | None,
    job_id: str,
    description: str,
) -> Path | None:
    """Write job description to `jobs/{job_id}/GOAL.md`.

    Args:
        jobs_root: Job artifact root (typically `$SOOTHE_DATA_DIR/jobs`).
        job_id: Root goal / job id.
        description: Submit description body (UTF-8 markdown text).

    Returns:
        Path written, or None when `jobs_root` is unset or write fails.
    """
    if jobs_root is None:
        return None
    text = description if description is not None else ""
    try:
        path = resolve_job_goal_md_path(jobs_root=jobs_root, job_id=job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path
    except (OSError, ValueError) as exc:
        logger.warning(
            "Failed to write job GOAL.md for %s: %s",
            job_id,
            exc,
        )
        return None


def load_job_goal_md(
    *,
    jobs_root: Path | None,
    job_id: str | None,
    max_chars: int = 800,
) -> str:
    """Read job-scoped GOAL.md excerpt, or empty string."""
    if jobs_root is None or not job_id or not str(job_id).strip():
        return ""
    try:
        path = resolve_job_goal_md_path(jobs_root=jobs_root, job_id=job_id)
    except ValueError:
        return ""
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")[:max_chars].strip()
    except OSError:
        return ""
