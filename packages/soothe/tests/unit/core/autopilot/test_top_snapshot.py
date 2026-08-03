"""Unit tests for autopilot top snapshot filters (IG-679)."""

from __future__ import annotations

from soothe.autopilot.top_snapshot import (
    build_top_job_entry,
    filter_active_dag,
    filter_active_loops,
)


def test_filter_active_dag_omits_terminal_and_prunes_edges() -> None:
    dag = {
        "root_id": "root1",
        "nodes": [
            {"id": "root1", "status": "active", "description": "root"},
            {"id": "child1", "status": "completed", "description": "done"},
            {"id": "child2", "status": "pending", "description": "todo"},
            {"id": "child3", "status": "failed", "description": "fail"},
        ],
        "edges": [
            {"source": "root1", "target": "child1"},
            {"source": "root1", "target": "child2"},
            {"source": "root1", "target": "child3"},
            {"source": "child1", "target": "child2"},
        ],
    }
    filtered = filter_active_dag(dag)
    assert filtered is not None
    ids = {n["id"] for n in filtered["nodes"]}
    assert ids == {"root1", "child2"}
    assert filtered["edges"] == [{"source": "root1", "target": "child2"}]
    assert filtered["root_id"] == "root1"


def test_filter_active_dag_returns_none_when_all_terminal() -> None:
    dag = {
        "nodes": [
            {"id": "a", "status": "completed"},
            {"id": "b", "status": "cancelled"},
        ],
        "edges": [{"source": "a", "target": "b"}],
    }
    assert filter_active_dag(dag) is None


def test_filter_active_dag_keeps_suspended() -> None:
    dag = {
        "nodes": [{"id": "a", "status": "suspended"}],
        "edges": [],
    }
    filtered = filter_active_dag(dag)
    assert filtered is not None
    assert filtered["nodes"][0]["id"] == "a"


def test_filter_active_loops() -> None:
    loops = [
        {"loop_id": "L1", "status": "active", "goal_id": "g1"},
        {"loop_id": "L2", "status": "completed", "goal_id": "g2"},
        {"loop_id": "L3", "status": "interrupted", "goal_id": "g3"},
    ]
    assert filter_active_loops(loops) == [loops[0]]


def test_build_top_job_entry_none_when_fully_terminal() -> None:
    entry = build_top_job_entry(
        job_id="j1",
        status="completed",
        priority=50,
        description="done",
        workspace=None,
        dag={
            "root_id": "j1",
            "nodes": [{"id": "j1", "status": "completed"}],
            "edges": [],
        },
        loops=[{"loop_id": "L1", "status": "active", "goal_id": "j1"}],
    )
    assert entry is None


def test_build_top_job_entry_includes_active_loops_and_workspace() -> None:
    entry = build_top_job_entry(
        job_id="j1",
        status="active",
        priority=80,
        description="Implement auth",
        workspace="/ws",
        dag={
            "root_id": "j1",
            "nodes": [
                {"id": "j1", "status": "active", "description": "Implement auth"},
                {"id": "g2", "status": "pending", "description": "tests"},
            ],
            "edges": [{"source": "j1", "target": "g2"}],
        },
        loops=[
            {
                "seq": 3,
                "loop_id": "autopilot__j1__abc",
                "goal_id": "j1",
                "status": "active",
            },
            {
                "seq": 2,
                "loop_id": "autopilot__j1__old",
                "goal_id": "j1",
                "status": "completed",
            },
        ],
    )
    assert entry is not None
    assert entry["id"] == "j1"
    assert entry["workspace"] == "/ws"
    assert entry["priority"] == 80
    assert len(entry["dag"]["nodes"]) == 2
    assert entry["loops"] == [
        {
            "seq": 3,
            "loop_id": "autopilot__j1__abc",
            "goal_id": "j1",
            "status": "active",
        }
    ]


def test_build_top_job_keeps_job_when_root_terminal_but_child_active() -> None:
    entry = build_top_job_entry(
        job_id="j1",
        status="completed",
        priority=50,
        description="root",
        workspace=None,
        dag={
            "root_id": "j1",
            "nodes": [
                {"id": "j1", "status": "completed"},
                {"id": "g2", "status": "active"},
            ],
            "edges": [{"source": "j1", "target": "g2"}],
        },
        loops=[],
    )
    assert entry is not None
    assert {n["id"] for n in entry["dag"]["nodes"]} == {"g2"}
    assert entry["dag"]["edges"] == []
    assert "workspace" not in entry
