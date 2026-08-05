"""Autopilot forest helpers for CLI ``top`` (RFC-228 / IG-679 / IG-688).

Pure filter/assembly used by ``AutopilotService.top_snapshot``. Server SoT for
which jobs/goals/loops appear in the live dashboard (active-only by default;
optional ``include_terminal`` keeps completed/failed/cancelled goals).
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


def _copy_dag(dag: dict[str, Any]) -> dict[str, Any]:
    """Shallow-copy ``nodes``/``edges`` (and optional ``root_id``) for a job row."""
    out: dict[str, Any] = {
        "nodes": list(dag.get("nodes") or []),
        "edges": list(dag.get("edges") or []),
    }
    if "root_id" in dag:
        out["root_id"] = dag["root_id"]
    return out


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
    include_terminal: bool = False,
) -> dict[str, Any] | None:
    """Assemble one job row for ``autopilot_top``, or ``None`` if omitted.

    Args:
        job_id: Root goal id.
        status: Root goal status.
        priority: Root priority.
        description: Root description.
        workspace: Optional workspace path.
        dag: Full DAG snapshot for the job.
        loops: JobLoopIndex entries (any status).
        created_at: Optional root ``created_at`` ISO timestamp.
        include_terminal: When ``False`` (default), drop terminal goals and
            fully terminal jobs. When ``True``, keep the full DAG.

    Returns:
        Job dict with filtered ``dag`` and active ``loops``, or ``None``.
    """
    if include_terminal:
        if not any(isinstance(n, dict) and n.get("id") for n in (dag.get("nodes") or [])):
            return None
        filtered = _copy_dag(dag)
    else:
        maybe = filter_active_dag(dag)
        if maybe is None:
            return None
        filtered = maybe

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
