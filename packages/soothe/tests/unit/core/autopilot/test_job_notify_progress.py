"""IG-713: compact job notify progress (counts + capped highlights)."""

from __future__ import annotations

from soothe.autopilot.notify.progress import (
    DEFAULT_MAX_HIGHLIGHTS,
    build_job_notify_progress,
    format_progress_plain,
)


def _dag(*nodes: dict) -> dict:
    return {"root_id": nodes[0]["id"] if nodes else None, "nodes": list(nodes)}


def test_progress_counts_without_listing_all_goals() -> None:
    nodes = [
        {"id": "root0001", "status": "completed", "description": "Job root"},
        {"id": "g001", "status": "completed", "description": "ok1", "role": "implement"},
        {"id": "g002", "status": "completed", "description": "ok2"},
        {"id": "g003", "status": "failed", "description": "boom", "role": "verify"},
        {"id": "g004", "status": "pending", "description": "wait"},
        {"id": "g005", "status": "suspended", "description": "paused"},
    ]
    # Pad with many completed goals — must not appear in highlights.
    for i in range(40):
        nodes.append({"id": f"pad{i:04d}", "status": "completed", "description": f"pad {i}"})

    progress = build_job_notify_progress(_dag(*nodes))
    assert progress is not None
    assert progress["total_goals"] == 46
    assert progress["completed_goals"] == 43
    assert progress["failed_goals"] == 1
    assert progress["pending_goals"] == 1
    assert progress["suspended_goals"] == 1
    assert progress["pct_complete"] == round(100.0 * 43 / 46)
    # Only attention statuses, capped — never the 40+ completed pads.
    assert len(progress["highlights"]) <= DEFAULT_MAX_HIGHLIGHTS
    highlight_ids = {h["id"] for h in progress["highlights"]}
    assert "g003" in highlight_ids
    assert "g005" in highlight_ids
    assert not any(hid.startswith("pad") for hid in highlight_ids)
    assert all(
        h["status"] in {"failed", "cancelled", "active", "suspended"}
        for h in progress["highlights"]
    )


def test_progress_caps_highlights_and_reports_omitted() -> None:
    nodes = [{"id": "root", "status": "active", "description": "root"}]
    for i in range(12):
        nodes.append(
            {
                "id": f"fail{i:02d}",
                "status": "failed",
                "description": f"fail {i}",
                "role": "maker",
            }
        )
    progress = build_job_notify_progress(_dag(*nodes), max_highlights=5)
    assert progress is not None
    assert len(progress["highlights"]) == 5
    assert progress["highlights_omitted"] == 8  # 12 failed + root active - 5
    assert progress["failed_goals"] == 12


def test_progress_none_for_empty_dag() -> None:
    assert build_job_notify_progress(None) is None
    assert build_job_notify_progress({"nodes": []}) is None


def test_format_progress_plain_includes_counts_not_full_list() -> None:
    progress = build_job_notify_progress(
        _dag(
            {"id": "root", "status": "failed", "description": "Job"},
            {"id": "a1", "status": "failed", "description": "child fail", "role": "qa"},
            {"id": "b1", "status": "completed", "description": "done"},
        )
    )
    lines = format_progress_plain(progress)
    text = "\n".join(lines)
    assert "Progress: 1/3 goals" in text
    assert "failed=2" in text
    assert "Needs attention:" in text
    assert "a1" in text
    assert "done" not in text  # completed not listed
