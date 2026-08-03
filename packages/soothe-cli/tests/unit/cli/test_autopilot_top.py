"""Unit tests for autopilot top CLI rendering (IG-679)."""

from __future__ import annotations

from soothe_cli.cli.commands.autopilot_cmd import render_top_snapshot


def test_render_top_empty() -> None:
    text = render_top_snapshot(
        {
            "running": True,
            "dreaming": False,
            "loop_pool": {"active": 0, "idle": 0, "max": 4},
            "jobs": [],
        },
        interval=1.0,
    )
    assert "No active jobs." in text
    assert "pool 0/0/4" in text
    assert "Ctrl+C quit · refresh 1s" in text


def test_render_top_forest_nests_loops() -> None:
    text = render_top_snapshot(
        {
            "running": True,
            "dreaming": False,
            "loop_pool": {"active": 1, "idle": 0, "max": 4},
            "jobs": [
                {
                    "id": "a1b2c3d4",
                    "status": "active",
                    "priority": 50,
                    "description": "Implement auth",
                    "dag": {
                        "root_id": "a1b2c3d4",
                        "nodes": [
                            {
                                "id": "a1b2c3d4",
                                "status": "active",
                                "description": "Implement auth",
                                "steps_completed": 1,
                                "steps_total": 4,
                            },
                            {
                                "id": "e5f6aaaa",
                                "status": "pending",
                                "description": "Write tests",
                            },
                        ],
                        "edges": [{"source": "a1b2c3d4", "target": "e5f6aaaa"}],
                    },
                    "loops": [
                        {
                            "seq": 3,
                            "loop_id": "autopilot__a1b2c3d4__" + "deadbeef" * 4,
                            "goal_id": "a1b2c3d4",
                            "status": "active",
                        }
                    ],
                }
            ],
        },
        interval=2.5,
    )
    assert '[a1b2c3d4] active     pri=50  "Implement auth"' in text
    assert "steps 1/4" in text
    assert "Write tests" in text
    assert "loop autopilot__a1b2c3d4__deadbeef…" in text
    assert "#3" in text
    assert "refresh 2.5s" in text


def test_render_top_orphan_loop_marker() -> None:
    text = render_top_snapshot(
        {
            "running": True,
            "loop_pool": {"active": 1, "idle": 0, "max": 2},
            "jobs": [
                {
                    "id": "rootroot",
                    "status": "active",
                    "priority": 10,
                    "description": "job",
                    "dag": {
                        "root_id": "rootroot",
                        "nodes": [
                            {"id": "rootroot", "status": "active", "description": "job"},
                        ],
                        "edges": [],
                    },
                    "loops": [
                        {
                            "seq": 1,
                            "loop_id": "autopilot__rootroot__" + "c" * 32,
                            "goal_id": "missing1",
                            "status": "active",
                        }
                    ],
                }
            ],
        },
        interval=1.0,
    )
    assert "?goal=missing1" in text
