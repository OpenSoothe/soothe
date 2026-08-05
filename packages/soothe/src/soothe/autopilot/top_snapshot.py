"""Active-only autopilot forest helpers for CLI ``top`` (RFC-228 / IG-679).

Pure filter/assembly used by ``AutopilotService.top_snapshot``. Server SoT for
which jobs/goals/loops appear in the live dashboard.
"""

from __future__ import annotations

from typing import Any

from soothe.context.models import TERMINAL_STATES


def filter_active_dag(dag: dict[str, Any]) -> dict[str, Any] | None:
    """Keep non-terminal goal nodes and edges that still connect them.

    Args:
        dag: Snapshot with ``nodes``, ``edges``, and optional ``root_id``.

    Returns:
        Filtered DAG dict, or ``None`` when no non-terminal nodes remain.
    """
    nodes_in = dag.get("nodes") or []
    nodes = [
        n
        for n in nodes_in
        if isinstance(n, dict) and str(n.get("status", "")) not in TERMINAL_STATES
    ]
    if not nodes:
        return None
    keep = {str(n["id"]) for n in nodes if n.get("id") is not None}
    edges = [
        e
        for e in (dag.get("edges") or [])
        if isinstance(e, dict)
        and str(e.get("source", "")) in keep
        and str(e.get("target", "")) in keep
    ]
    out: dict[str, Any] = {
        "nodes": nodes,
        "edges": edges,
    }
    if "root_id" in dag:
        out["root_id"] = dag["root_id"]
    return out


def filter_active_loops(loops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return JobLoopIndex entries with ``status == "active"``."""
    return [entry for entry in loops if isinstance(entry, dict) and entry.get("status") == "active"]


def build_top_job_entry(
    *,
    job_id: str,
    status: str,
    priority: int,
    description: str,
    workspace: str | None,
    dag: dict[str, Any],
    loops: list[dict[str, Any]],
    created_at: str | None = None,
) -> dict[str, Any] | None:
    """Assemble one job row for ``autopilot_top``, or ``None`` if fully terminal.

    Args:
        job_id: Root goal id.
        status: Root goal status.
        priority: Root priority.
        description: Root description.
        workspace: Optional workspace path.
        dag: Full DAG snapshot for the job.
        loops: JobLoopIndex entries (any status).
        created_at: Optional root ``created_at`` ISO timestamp.

    Returns:
        Job dict with filtered ``dag`` and active ``loops``, or ``None``.
    """
    filtered = filter_active_dag(dag)
    if filtered is None:
        return None
    entry: dict[str, Any] = {
        "id": job_id,
        "status": status,
        "priority": priority,
        "description": description,
        "dag": filtered,
        "loops": filter_active_loops(loops),
    }
    if workspace:
        entry["workspace"] = workspace
    if created_at:
        entry["created_at"] = created_at
    return entry
