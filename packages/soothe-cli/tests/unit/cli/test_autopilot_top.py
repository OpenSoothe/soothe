"""Unit tests for autopilot top CLI rendering (IG-679 / IG-686)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from soothe_cli.cli.commands.autopilot_cmd import format_elapsed, render_top_snapshot


def test_format_elapsed_hhmmss() -> None:
    now = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
    started = now - timedelta(hours=1, minutes=2, seconds=3)
    assert format_elapsed(started.isoformat(), now=now) == "01:02:03"
    assert format_elapsed(None) == ""
    assert format_elapsed("") == ""


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


def test_render_top_forest_nests_steps_and_loops() -> None:
    now = datetime(2026, 8, 5, 1, 2, 0, tzinfo=UTC)
    started = (now - timedelta(minutes=3, seconds=21)).isoformat()
    created = (now - timedelta(minutes=12, seconds=34)).isoformat()
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
                    "created_at": created,
                    "dag": {
                        "root_id": "a1b2c3d4",
                        "nodes": [
                            {
                                "id": "a1b2c3d4",
                                "status": "active",
                                "description": "Implement auth",
                                "steps_completed": 1,
                                "steps_total": 2,
                                "steps": {
                                    "nodes": [
                                        {
                                            "id": "UZH-01",
                                            "status": "completed",
                                            "description": "Scaffold routes",
                                            "dependencies": [],
                                        },
                                        {
                                            "id": "UZH-02",
                                            "status": "pending",
                                            "description": "Add JWT",
                                            "dependencies": ["UZH-01"],
                                        },
                                    ],
                                    "edges": [{"source": "UZH-01", "target": "UZH-02"}],
                                },
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
                            "started_at": started,
                        }
                    ],
                }
            ],
        },
        interval=2.5,
    )
    # Patch elapsed by checking format with known now via direct helper
    assert format_elapsed(created, now=now) == "00:12:34"
    assert format_elapsed(started, now=now) == "00:03:21"
    assert "pri=50" in text
    assert "Implement auth" in text
    assert "steps 1/2" in text
    assert "[UZH-01] completed" in text or "[UZH-01] completed" in text
    assert "Add JWT" in text
    assert "Write tests" in text
    assert "loop autopilot__a1b2c3d4__deadbeef…" in text
    assert "#3" in text
    assert "refresh 2.5s" in text


def test_render_top_pads_to_height() -> None:
    text = render_top_snapshot(
        {
            "running": True,
            "loop_pool": {"active": 0, "idle": 0, "max": 2},
            "jobs": [],
        },
        interval=1.0,
        width=40,
        height=12,
    )
    assert len(text.splitlines()) == 12


def test_render_top_multiline_descriptions_stay_one_line() -> None:
    text = render_top_snapshot(
        {
            "running": True,
            "loop_pool": {"active": 0, "idle": 0, "max": 2},
            "jobs": [
                {
                    "id": "fad4717e",
                    "status": "pending",
                    "priority": 70,
                    "description": "Task: Initial C Compiler Scaffold\nBuilding the compiler frontend",
                    "dag": {
                        "root_id": "fad4717e",
                        "nodes": [
                            {
                                "id": "fad4717e",
                                "status": "pending",
                                "description": (
                                    "Task: Initial C Compiler Scaffold\n"
                                    "Building the compiler frontend"
                                ),
                            },
                        ],
                        "edges": [],
                    },
                    "loops": [],
                }
            ],
        },
        interval=1.0,
    )
    assert "\nBuilding" not in text
    job_line = next(ln for ln in text.splitlines() if ln.startswith("[fad4717e]"))
    assert "pri=70" in job_line
    assert "Task: Initial C Compiler Scaffold Building" in job_line
    goal_line = next(ln for ln in text.splitlines() if ln.startswith("└─ [fad4717e]"))
    assert "Task: Initial C Compiler Scaffold Building" in goal_line
    assert "\n" not in job_line
    assert "\n" not in goal_line


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
