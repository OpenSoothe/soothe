"""Unit tests for autopilot top CLI rendering (IG-679 / IG-686 / IG-688 / IG-694 / IG-698)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from soothe_cli.cli.commands.autopilot_cmd import (
    _STYLE_ACTIVE,
    _STYLE_DIM,
    _STYLE_DONE,
    _STYLE_HOT,
    _STYLE_WARN,
    TopViewState,
    _format_top_header,
    _meter_fill_style,
    _status_style,
    aggregate_top_stats,
    apply_top_key,
    decode_top_csi,
    format_elapsed,
    format_tokens,
    render_top_snapshot,
)


def _plain(snapshot: dict, **kwargs: object) -> str:
    return render_top_snapshot(snapshot, **kwargs).plain  # type: ignore[arg-type]


def test_meter_fill_style_util_vs_progress() -> None:
    """Util meters redden under load; progress meters go green when complete."""
    assert _meter_fill_style(1.0, kind="util") == _STYLE_HOT
    assert _meter_fill_style(0.9, kind="util") == _STYLE_HOT
    assert _meter_fill_style(0.6, kind="util") == _STYLE_WARN
    assert _meter_fill_style(0.2, kind="util") == _STYLE_ACTIVE

    assert _meter_fill_style(1.0, kind="progress") == _STYLE_ACTIVE
    assert _meter_fill_style(0.9, kind="progress") == _STYLE_DONE
    assert _meter_fill_style(0.6, kind="progress") == _STYLE_DONE
    assert _meter_fill_style(0.2, kind="progress") == _STYLE_WARN
    assert _meter_fill_style(0.0, kind="progress") == _STYLE_DIM


def test_status_style_completed_is_green() -> None:
    assert _status_style("completed") == _STYLE_DONE
    assert _status_style("active") == _STYLE_ACTIVE
    assert _status_style("failed") == _STYLE_HOT


def test_render_top_all_goals_done_uses_progress_green() -> None:
    """All-done Goals/Steps meters use progress green (not util red)."""
    snapshot = {
        "running": True,
        "dreaming": False,
        "loop_pool": {"active": 0, "idle": 4, "max": 4},
        "jobs": [
            {
                "id": "donejob01",
                "status": "completed",
                "created_at": "2026-08-05T12:00:00+00:00",
                "dag": {
                    "nodes": [
                        {
                            "id": "g1",
                            "status": "completed",
                            "steps_completed": 2,
                            "steps_total": 2,
                        }
                    ]
                },
                "loops": [],
            }
        ],
    }
    state = TopViewState(include_terminal=True)
    header = _format_top_header(snapshot, state=state, width=80)
    goals = next(line for line in header if line.plain.startswith("Goals"))
    steps = next(line for line in header if line.plain.startswith("Steps"))
    assert "done=1" in goals.plain
    assert "2/2 done" in steps.plain
    goals_fill = {
        str(span.style) for span in goals.spans if "█" in goals.plain[span.start : span.end]
    }
    steps_fill = {
        str(span.style) for span in steps.spans if "█" in steps.plain[span.start : span.end]
    }
    assert goals_fill == {_STYLE_ACTIVE}
    assert steps_fill == {_STYLE_ACTIVE}
    assert _STYLE_HOT not in {str(span.style) for span in goals.spans}
    assert _STYLE_HOT not in {str(span.style) for span in steps.spans}


def test_format_elapsed_hhmmss() -> None:
    now = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
    started = now - timedelta(hours=1, minutes=2, seconds=3)
    assert format_elapsed(started.isoformat(), now=now) == "01:02:03"
    assert format_elapsed(None) == ""
    assert format_elapsed("") == ""


def test_format_tokens() -> None:
    assert format_tokens(0) == "0"
    assert format_tokens(999) == "999"
    assert format_tokens(1500) == "1K"
    assert format_tokens(2_500_000) == "2M"
    assert format_tokens(None) == "0"


def test_top_view_state_defaults() -> None:
    state = TopViewState()
    assert state.show_steps is True
    assert state.show_loops is True
    assert state.interval == 2.0
    assert state.include_terminal is False
    assert state.page_size == 1


def test_render_top_empty() -> None:
    text = _plain(
        {
            "running": True,
            "dreaming": False,
            "loop_pool": {"active": 0, "idle": 0, "max": 4},
            "jobs": [],
        },
        interval=2.0,
    )
    assert "No active jobs." in text
    assert "Jobs" in text and "0 total" in text
    assert "Goals" in text
    assert "Loops" in text
    assert "0/0/4" in text
    assert "(active/idle/max)" in text
    assert "0 assigned" in text
    assert "mode=active" in text
    assert "(live)" in text
    assert "q Quit" in text
    assert "refresh 2s" in text
    assert "steps=on" in text
    assert "loops=on" in text
    assert "legend" not in text
    # Empty forest: no Steps row (only when steps_total > 0).
    assert "Steps" not in text.split("mode=")[0]


def test_aggregate_top_stats_counts() -> None:
    stats = aggregate_top_stats(
        {
            "loop_pool": {"active": 1, "idle": 0, "max": 4},
            "jobs": [
                {
                    "id": "job-a",
                    "status": "active",
                    "created_at": "2026-08-05T12:00:00+00:00",
                    "dag": {
                        "nodes": [
                            {
                                "id": "job-a",
                                "status": "active",
                                "steps_completed": 1,
                                "steps_total": 3,
                            },
                            {
                                "id": "g2",
                                "status": "pending",
                                "steps_completed": 0,
                                "steps_total": 2,
                            },
                            {"id": "g3", "status": "completed"},
                        ]
                    },
                    "loops": [{"loop_id": "L1", "status": "active"}],
                },
                {
                    "id": "job-b",
                    "status": "pending",
                    "created_at": "2026-08-05T11:00:00+00:00",
                    "dag": {"nodes": [{"id": "job-b", "status": "pending"}]},
                    "loops": [],
                },
            ],
        }
    )
    assert stats["jobs_total"] == 2
    assert stats["jobs_active"] == 1
    assert stats["jobs_by_status"]["pending"] == 1
    assert stats["goals_total"] == 4
    assert stats["goals_active"] == 1
    assert stats["goals_completed"] == 1
    assert stats["loops_assigned"] == 1
    assert stats["loop_pool_active"] == 1
    assert stats["steps_completed"] == 1
    assert stats["steps_total"] == 5
    assert stats["oldest_created_at"] == "2026-08-05T11:00:00+00:00"


def test_decode_top_csi() -> None:
    assert decode_top_csi("[A") == "up"
    assert decode_top_csi("[B") == "down"
    assert decode_top_csi("[5~") == "page_up"
    assert decode_top_csi("[6~") == "page_down"
    assert decode_top_csi("[H") == "home"
    assert decode_top_csi("[F") == "end"
    assert decode_top_csi("[1~") == "home"
    assert decode_top_csi("OH") == "home"
    assert decode_top_csi("[Z") is None


def test_apply_top_key_vim_scroll() -> None:
    state = TopViewState(page_size=10, body_line_count=100, scroll=20)
    apply_top_key(state, "ctrl_d")
    assert state.scroll == 25  # half of 10
    apply_top_key(state, "ctrl_u")
    assert state.scroll == 20
    apply_top_key(state, "ctrl_f")
    assert state.scroll == 30
    apply_top_key(state, "page_down")
    assert state.scroll == 40
    apply_top_key(state, "ctrl_b")
    assert state.scroll == 30
    apply_top_key(state, "page_up")
    assert state.scroll == 20
    apply_top_key(state, "ctrl_e")
    assert state.scroll == 21
    apply_top_key(state, "ctrl_y")
    assert state.scroll == 20
    apply_top_key(state, "home")
    assert state.scroll == 0
    apply_top_key(state, "end")
    assert state.scroll == 100
    apply_top_key(state, "g")
    assert state.scroll == 0
    apply_top_key(state, "G")
    assert state.scroll == 100


def test_render_top_sets_page_size() -> None:
    state = TopViewState()
    # Empty forest header: title + Jobs + Goals + Loops + flags + rule = 6
    # (+ footer 2) → max_body = height - 8; page_size = max_body - 1
    render_top_snapshot(
        {"running": True, "loop_pool": {"active": 0, "idle": 0, "max": 1}, "jobs": []},
        height=20,
        width=80,
        state=state,
    )
    assert state.page_size == max(1, 20 - 6 - 2 - 1)


def test_apply_top_key_toggles() -> None:
    state = TopViewState()
    assert state.show_steps is True and state.show_loops is True
    assert state.interval == 2.0
    apply_top_key(state, "a")
    assert state.include_terminal is True
    assert state.force_refresh is True
    apply_top_key(state, "s")
    assert state.show_steps is False
    apply_top_key(state, "l")
    assert state.show_loops is False
    # density from compact: steps-only → full → compact → steps-only
    apply_top_key(state, "d")
    assert state.show_steps is True and state.show_loops is False
    apply_top_key(state, "d")
    assert state.show_steps is True and state.show_loops is True
    apply_top_key(state, "d")
    assert state.show_steps is False and state.show_loops is False
    apply_top_key(state, "+")
    assert state.interval == 1.5
    apply_top_key(state, "q")
    assert state.quit is True
    state.help_open = True
    apply_top_key(state, "x")
    assert state.help_open is False


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
                    "total_tokens_used": 12500,
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
        state=TopViewState(show_steps=True, show_loops=True, interval=2.5),
    )
    text = rendered.plain
    # Patch elapsed by checking format with known now via direct helper
    assert format_elapsed(created, now=now) == "00:12:34"
    assert format_elapsed(started, now=now) == "00:03:21"
    assert "pri=50" in text
    assert "tok=12K" in text
    assert "Implement auth" in text
    assert "steps 1/2" in text
    assert "JOB  [a1b2c3d4]" in text
    assert "GOAL [a1b2c3d4]" in text
    # steps=on lists full StepDAG under live goals (including completed).
    assert "STEP [UZH-01]" in text
    assert "STEP [UZH-02]" in text
    assert "Add JWT" in text
    assert "←UZH-01" in text  # flat list keeps deps inline, not nested tree
    assert "Write tests" in text
    # Steps are a flat list (same indent), not a nested step tree.
    step_lines = [ln for ln in text.splitlines() if "STEP [" in ln]
    assert len(step_lines) == 2
    assert "LOOP autopilot__a1b2c3d4__deadbeef…" in text
    assert "#3" in text
    assert "refresh 2.5s" in text
    assert "bright_cyan" in rendered.markup
    assert "mode=active" in text
    assert "(live)" in text
    # htop-style header aggregates from the forest
    assert "Jobs" in text and "active=1" in text
    assert "Goals" in text and "pending=1" in text
    assert "Loops" in text and "1/0/4" in text and "1 assigned" in text
    assert "Steps" in text and "1/2 done" in text
    assert "up " in text  # oldest-job uptime on title line


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


def test_render_top_steps_on_shows_full_stepdag_for_live_goals() -> None:
    """steps=on lists completed/active/skipped STEPs under goals still in the forest."""
    snap = {
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
                            "steps_total": 3,
                            "steps": {
                                "nodes": [
                                    {
                                        "id": "UZH-01",
                                        "status": "completed",
                                        "description": "Scaffold",
                                        "dependencies": [],
                                    },
                                    {
                                        "id": "UZH-02",
                                        "status": "active",
                                        "description": "Add JWT",
                                        "dependencies": ["UZH-01"],
                                    },
                                    {
                                        "id": "UZH-03",
                                        "status": "skipped",
                                        "description": "Docs",
                                        "dependencies": [],
                                    },
                                ],
                                "edges": [],
                            },
                        }
                    ],
                    "edges": [],
                },
                "loops": [],
            }
        ],
    }
    active = _plain(snap, state=TopViewState(include_terminal=False, show_steps=True))
    assert "STEP [UZH-01]" in active
    assert "STEP [UZH-02]" in active
    assert "STEP [UZH-03]" in active
    assert "mode=active" in active
    assert "(live)" in active

    all_mode = _plain(snap, state=TopViewState(include_terminal=True, show_steps=True))
    assert "STEP [UZH-01]" in all_mode
    assert "STEP [UZH-02]" in all_mode
    assert "STEP [UZH-03]" in all_mode
    assert "mode=all" in all_mode
    assert "(live)" not in all_mode


def test_render_top_active_goal_all_completed_steps_still_listed() -> None:
    """Live goal with steps N/N must still show STEP rows when steps=on."""
    text = _plain(
        {
            "running": True,
            "loop_pool": {"active": 1, "idle": 0, "max": 4},
            "jobs": [
                {
                    "id": "a1b2c3d4",
                    "status": "active",
                    "priority": 50,
                    "description": "Quality gate",
                    "dag": {
                        "root_id": "a1b2c3d4",
                        "nodes": [
                            {
                                "id": "a1b2c3d4",
                                "status": "active",
                                "description": "Quality gate",
                                "steps_completed": 2,
                                "steps_total": 2,
                                "steps": {
                                    "nodes": [
                                        {
                                            "id": "JNC-01",
                                            "status": "completed",
                                            "description": "Review diff",
                                            "dependencies": [],
                                        },
                                        {
                                            "id": "JNC-02",
                                            "status": "completed",
                                            "description": "Gate decision",
                                            "dependencies": ["JNC-01"],
                                        },
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
        state=TopViewState(include_terminal=False, show_steps=True, show_loops=True),
    )
    assert "steps 2/2" in text
    assert "STEP [JNC-01] completed" in text
    assert "STEP [JNC-02] completed" in text
    assert "LOOP autopilot__a1b2c3d4__deadbeef" in text


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
        state=TopViewState(show_steps=True, show_loops=True, interval=1.0),
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
