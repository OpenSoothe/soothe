"""Autopilot forest helpers for CLI ``top`` (RFC-228 / IG-679 / IG-688).

Pure filter/assembly used by ``AutopilotService.top_snapshot``. Server SoT for
which jobs/goals/loops appear in the live dashboard (active-only by default;
optional ``include_terminal`` keeps completed/failed/cancelled goals and
terminal steps).
"""

from __future__ import annotations

from typing import Any

from soothe.context.models import TERMINAL_STATES

# StepDAG terminal statuses (mode=active hides these; mode=all keeps them).
STEP_TERMINAL_STATES: frozenset[str] = frozenset({"completed", "failed", "skipped"})


def filter_active_steps(steps: dict[str, Any]) -> dict[str, Any] | None:
    """Keep non-terminal step nodes and edges that still connect them.

    Args:
        steps: StepDAG snapshot with ``nodes`` and optional ``edges``.

    Returns:
        Filtered steps dict, or ``None`` when no non-terminal steps remain.
    """
    nodes_in = steps.get("nodes") or []
    nodes = [
        n
        for n in nodes_in
        if isinstance(n, dict)
        and n.get("id") is not None
        and str(n.get("status", "pending")) not in STEP_TERMINAL_STATES
    ]
    if not nodes:
        return None
    keep = {str(n["id"]) for n in nodes}
    edges = [
        e
        for e in (steps.get("edges") or [])
        if isinstance(e, dict)
        and str(e.get("source", "")) in keep
        and str(e.get("target", "")) in keep
    ]
    return {"nodes": nodes, "edges": edges}


def _with_active_steps(node: dict[str, Any]) -> dict[str, Any]:
    """Shallow-copy a goal node with terminal steps stripped (counts preserved)."""
    steps = node.get("steps")
    if not isinstance(steps, dict):
        return node
    filtered = filter_active_steps(steps)
    out = dict(node)
    if filtered is None:
        out.pop("steps", None)
    else:
        out["steps"] = filtered
    return out


def filter_active_dag(dag: dict[str, Any]) -> dict[str, Any] | None:
    """Keep non-terminal goal nodes and edges that still connect them.

    Also strips terminal StepDAG rows under kept goals (``completed`` /
    ``failed`` / ``skipped``). Goal ``steps_completed`` / ``steps_total``
    counters are left unchanged.

    Args:
        dag: Snapshot with ``nodes``, ``edges``, and optional ``root_id``.

    Returns:
        Filtered DAG dict, or ``None`` when no non-terminal nodes remain.
    """
    nodes_in = dag.get("nodes") or []
    nodes = [
        _with_active_steps(n)
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


def derive_top_running_status(
    root_status: str,
    *,
    nodes: list[dict[str, Any]],
    loops: list[dict[str, Any]],
) -> str:
    """Effective status for top when a rail root stays ``pending`` while work runs.

    Rail job roots are coordinators and often remain ``pending`` while child
    goals / loops execute. Surface ``active`` (or clarification/suspend) so the
    live forest does not look idle.
    """
    if root_status in TERMINAL_STATES:
        return root_status
    if any(isinstance(entry, dict) and entry.get("status") == "active" for entry in loops):
        return "active"
    statuses = {
        str(n.get("status", ""))
        for n in nodes
        if isinstance(n, dict) and n.get("status") is not None
    }
    if "active" in statuses:
        return "active"
    if "awaiting_clarification" in statuses:
        return "awaiting_clarification"
    if "blocked" in statuses:
        return "blocked"
    if "suspended" in statuses and not (statuses & {"pending", "active"}):
        return "suspended"
    return root_status


def apply_top_running_status(
    entry: dict[str, Any],
    *,
    root_id: str | None = None,
) -> dict[str, Any]:
    """Mutate a top job entry so JOB/root GOAL reflect in-flight work."""
    dag = entry.get("dag") if isinstance(entry.get("dag"), dict) else {}
    nodes = [n for n in (dag.get("nodes") or []) if isinstance(n, dict)]
    loops = [L for L in (entry.get("loops") or []) if isinstance(L, dict)]
    effective = derive_top_running_status(
        str(entry.get("status") or "pending"),
        nodes=nodes,
        loops=loops,
    )
    entry["status"] = effective
    rid = str(root_id or dag.get("root_id") or entry.get("id") or "")
    if rid:
        for node in nodes:
            if str(node.get("id")) == rid and str(node.get("status")) not in TERMINAL_STATES:
                node["status"] = effective
                break
    return entry


def _job_recency_key(job: dict[str, Any]) -> tuple[float, str]:
    """Sort key for top jobs: newest ``created_at`` first; missing timestamps last."""
    from datetime import UTC, datetime

    raw = job.get("created_at")
    ts = float("-inf")
    if isinstance(raw, datetime):
        start = raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
        ts = start.timestamp()
    elif raw not in (None, ""):
        try:
            start = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            ts = start.timestamp()
        except (TypeError, ValueError):
            ts = float("-inf")
    # Negate so larger timestamps sort first; id breaks ties stably.
    return (-ts, str(job.get("id") or ""))


def sort_top_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order job rows newest-first for ``autopilot top`` (most recent on top)."""
    return sorted((j for j in jobs if isinstance(j, dict)), key=_job_recency_key)


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
    return apply_top_running_status(entry, root_id=job_id)
