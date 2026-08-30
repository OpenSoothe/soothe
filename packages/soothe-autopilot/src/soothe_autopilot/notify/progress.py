"""Compact job DAG progress for lifecycle notify.

Counts every goal; never attaches a full goal list. Only a small capped
set of attention highlights (failed / cancelled / active / suspended).
"""

from __future__ import annotations

from typing import Any

_STATUS_COUNT_KEYS: dict[str, str] = {
    "completed": "completed_goals",
    "failed": "failed_goals",
    "active": "active_goals",
    "pending": "pending_goals",
    "suspended": "suspended_goals",
    "cancelled": "cancelled_goals",
}

# Lower sort key = higher priority for highlight inclusion.
_HIGHLIGHT_PRIORITY: dict[str, int] = {
    "failed": 0,
    "cancelled": 1,
    "active": 2,
    "suspended": 3,
}

DEFAULT_MAX_HIGHLIGHTS = 5
_DESC_MAX = 120


def build_job_notify_progress(
    dag: dict[str, Any] | None,
    *,
    max_highlights: int = DEFAULT_MAX_HIGHLIGHTS,
) -> dict[str, Any] | None:
    """Build a compact progress summary from a job `dag_snapshot`.

    Args:
        dag: Snapshot with `nodes` (and optional `root_id`).
        max_highlights: Max attention rows (failed/cancelled/active/suspended).

    Returns:
        Progress dict, or `None` when `dag` has no usable nodes.
    """
    if not dag or not isinstance(dag, dict):
        return None
    nodes = [
        n
        for n in (dag.get("nodes") or [])
        if isinstance(n, dict) and str(n.get("id") or "").strip()
    ]
    if not nodes:
        return None

    counts: dict[str, int] = {
        "total_goals": 0,
        "completed_goals": 0,
        "failed_goals": 0,
        "active_goals": 0,
        "pending_goals": 0,
        "suspended_goals": 0,
        "cancelled_goals": 0,
    }
    candidates: list[tuple[int, dict[str, Any]]] = []

    for node in nodes:
        counts["total_goals"] += 1
        status = str(node.get("status") or "pending").lower()
        count_key = _STATUS_COUNT_KEYS.get(status)
        if count_key is not None:
            counts[count_key] += 1
        priority = _HIGHLIGHT_PRIORITY.get(status)
        if priority is not None:
            candidates.append((priority, node))

    candidates.sort(key=lambda item: (item[0], str(item[1].get("id") or "")))
    cap = max(0, int(max_highlights))
    selected = candidates[:cap]
    highlights = [_highlight_row(n) for _, n in selected]
    omitted = max(0, len(candidates) - len(highlights))

    total = counts["total_goals"]
    completed = counts["completed_goals"]
    pct = int(round(100.0 * completed / total)) if total else 0

    return {
        **counts,
        "pct_complete": pct,
        "highlights": highlights,
        "highlights_omitted": omitted,
    }


def _highlight_row(node: dict[str, Any]) -> dict[str, Any]:
    desc = str(node.get("description") or "").strip()
    if len(desc) > _DESC_MAX:
        desc = desc[: _DESC_MAX - 1] + "…"
    row: dict[str, Any] = {
        "id": str(node.get("id") or ""),
        "status": str(node.get("status") or ""),
        "description": desc,
    }
    role = node.get("role")
    if role:
        row["role"] = str(role)
    return row


def format_progress_plain(progress: dict[str, Any] | None) -> list[str]:
    """Plain-text lines for an email / IM body (no full goal dump)."""
    if not progress:
        return []
    total = int(progress.get("total_goals") or 0)
    completed = int(progress.get("completed_goals") or 0)
    pct = int(progress.get("pct_complete") or 0)
    lines = [
        f"Progress: {completed}/{total} goals ({pct}%)",
        (
            f"  completed={int(progress.get('completed_goals') or 0)} "
            f"failed={int(progress.get('failed_goals') or 0)} "
            f"active={int(progress.get('active_goals') or 0)} "
            f"pending={int(progress.get('pending_goals') or 0)} "
            f"suspended={int(progress.get('suspended_goals') or 0)} "
            f"cancelled={int(progress.get('cancelled_goals') or 0)}"
        ),
    ]
    highlights = progress.get("highlights") or []
    if not isinstance(highlights, list) or not highlights:
        return lines
    lines.append("")
    lines.append("Needs attention:")
    for raw in highlights:
        if not isinstance(raw, dict):
            continue
        short = str(raw.get("id") or "")[:8]
        status = str(raw.get("status") or "")
        role = str(raw.get("role") or "").strip()
        role_bit = f" [{role}]" if role else ""
        desc = str(raw.get("description") or "").strip()
        desc_bit = f" {desc}" if desc else ""
        lines.append(f"  - {short} ({status}){role_bit}{desc_bit}")
    omitted = int(progress.get("highlights_omitted") or 0)
    if omitted > 0:
        lines.append(f"  … ({omitted} more omitted)")
    return lines
