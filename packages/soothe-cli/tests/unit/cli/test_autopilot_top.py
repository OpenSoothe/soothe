"""Unit tests for autopilot top CLI rendering (IG-679 / IG-686 / IG-688)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from soothe_cli.cli.commands.autopilot_cmd import (
    TopViewState,
    apply_top_key,
    format_elapsed,
    render_top_snapshot,
)


def _plain(snapshot: dict, **kwargs: object) -> str:
    return render_top_snapshot(snapshot, **kwargs).plain  # type: ignore[arg-type]


def test_format_elapsed_hhmmss() -> None:
    now = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
    started = now - timedelta(hours=1, minutes=2, seconds=3)
    assert format_elapsed(started.isoformat(), now=now) == "01:02:03"
    assert format_elapsed(None) == ""
    assert format_elapsed("") == ""


def test_render_top_empty() -> None:
    text = _plain(
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
    assert "mode=active" in text
    assert "q Quit" in text
    assert "refresh 1s" in text
    assert "legend" in text
    assert "JOB" in text and "GOAL" in text and "STEP" in text and "LOOP" in text


def test_render_top_forest_nests_steps_and_loops() -> None:
    now = datetime(2026, 8, 5, 1, 2, 0, tzinfo=UTC)
    started = (now - timedelta(minutes=3, seconds=21)).isoformat()
    created = (now - timedelta(minutes=12, seconds=34)).isoformat()
    rendered = render_top_snapshot(
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
    text = rendered.plain
    # Patch elapsed by checking format with known now via direct helper
    assert format_elapsed(created, now=now) == "00:12:34"
    assert format_elapsed(started, now=now) == "00:03:21"
    assert "pri=50" in text
    assert "Implement auth" in text
    assert "steps 1/2" in text
    assert "JOB  [a1b2c3d4]" in text
    assert "GOAL [a1b2c3d4]" in text
    assert "STEP [UZH-01]" in text
    assert "Add JWT" in text
    assert "←UZH-01" in text  # flat list keeps deps inline, not nested tree
    assert "Write tests" in text
    # Steps are a flat list (same indent), not a nested step tree.
    step_lines = [ln for ln in text.splitlines() if "STEP [" in ln]
    assert len(step_lines) == 2
    assert all(ln.index("STEP") == step_lines[0].index("STEP") for ln in step_lines)
    assert "LOOP autopilot__a1b2c3d4__deadbeef…" in text
    assert "#3" in text
    assert "refresh 2.5s" in text
    assert "bright_cyan" in rendered.markup


def test_render_top_hides_steps_and_loops() -> None:
    state = TopViewState(show_steps=False, show_loops=False, interval=1.0)
    text = _plain(
        {
            "running": True,
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
                                "steps_total": 2,
                                "steps": {
                                    "nodes": [
                                        {
                                            "id": "UZH-01",
                                            "status": "completed",
                                            "description": "Scaffold",
                                            "dependencies": [],
                                        }
                                    ],
                                    "edges": [],
                                },
                            }
                        ],
                        "edges": [],
                    },
                    "loops": [
                        {
                            "seq": 1,
                            "loop_id": "autopilot__a1b2c3d4__deadbeef",
                            "goal_id": "a1b2c3d4",
                            "status": "active",
                        }
                    ],
                }
            ],
        },
        state=state,
    )
    assert "steps 1/2" in text
    assert "UZH-01" not in text
    assert "LOOP autopilot" not in text
    assert "STEP [UZH" not in text
    assert "steps=off" in text
    assert "loops=off" in text


def test_apply_top_key_toggles() -> None:
    state = TopViewState()
    apply_top_key(state, "a")
    assert state.include_terminal is True
    assert state.force_refresh is True
    apply_top_key(state, "s")
    assert state.show_steps is False
    apply_top_key(state, "l")
    assert state.show_loops is False
    apply_top_key(state, "d")
    assert state.show_steps is True and state.show_loops is False
    apply_top_key(state, "d")
    assert state.show_steps is True and state.show_loops is True
    apply_top_key(state, "d")
    assert state.show_steps is False and state.show_loops is False
    apply_top_key(state, "+")
    assert state.interval == 0.5
    apply_top_key(state, "q")
    assert state.quit is True
    state.help_open = True
    apply_top_key(state, "x")
    assert state.help_open is False


def test_render_top_pads_to_height() -> None:
    text = _plain(
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
    text = _plain(
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
    job_line = next(ln for ln in text.splitlines() if ln.startswith("JOB  [fad4717e]"))
    assert "pri=70" in job_line
    assert "Task: Initial C Compiler Scaffold Building" in job_line
    goal_line = next(ln for ln in text.splitlines() if "GOAL [fad4717e]" in ln)
    assert "Task: Initial C Compiler Scaffold Building" in goal_line
    assert "\n" not in job_line
    assert "\n" not in goal_line


def test_render_top_orphan_loop_marker() -> None:
    text = _plain(
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
    assert "LOOP " in text


def test_render_top_shows_active_not_pending_for_running_work() -> None:
    text = _plain(
        {
            "running": True,
            "loop_pool": {"active": 1, "idle": 0, "max": 16},
            "jobs": [
                {
                    "id": "jobjobj1",
                    "status": "active",
                    "priority": 55,
                    "description": "running job",
                    "created_at": "2026-08-05T12:00:00+00:00",
                    "dag": {
                        "root_id": "jobjobj1",
                        "nodes": [
                            {
                                "id": "jobjobj1",
                                "status": "active",
                                "description": "running job",
                                "steps_completed": 0,
                                "steps_total": 1,
                                "steps": {
                                    "nodes": [
                                        {
                                            "id": "S-01",
                                            "status": "active",
                                            "description": "doing work",
                                            "dependencies": [],
                                        }
                                    ],
                                    "edges": [],
                                },
                            }
                        ],
                        "edges": [],
                    },
                    "loops": [
                        {
                            "seq": 1,
                            "loop_id": "autopilot__jobjobj1__deadbeef",
                            "goal_id": "jobjobj1",
                            "status": "active",
                        }
                    ],
                }
            ],
        },
        interval=1.0,
    )
    assert "JOB  [jobjobj1] active" in text
    assert "GOAL [jobjobj1] active" in text
    assert "STEP [S-01] active" in text
    assert "LOOP autopilot__jobjobj1__deadbeef" in text
    assert "active  #1" in text


def test_render_top_jobs_newest_first() -> None:
    text = _plain(
        {
            "running": True,
            "loop_pool": {"active": 0, "idle": 0, "max": 2},
            "jobs": [
                {
                    "id": "aaaa1111",
                    "status": "pending",
                    "priority": 50,
                    "description": "older job",
                    "created_at": "2026-08-01T00:00:00+00:00",
                    "dag": {
                        "root_id": "aaaa1111",
                        "nodes": [
                            {"id": "aaaa1111", "status": "pending", "description": "older job"},
                        ],
                        "edges": [],
                    },
                    "loops": [],
                },
                {
                    "id": "bbbb2222",
                    "status": "active",
                    "priority": 50,
                    "description": "newer job",
                    "created_at": "2026-08-05T12:00:00+00:00",
                    "dag": {
                        "root_id": "bbbb2222",
                        "nodes": [
                            {"id": "bbbb2222", "status": "active", "description": "newer job"},
                        ],
                        "edges": [],
                    },
                    "loops": [],
                },
            ],
        },
        interval=1.0,
    )
    older = text.index("JOB  [aaaa1111]")
    newer = text.index("JOB  [bbbb2222]")
    assert newer < older
