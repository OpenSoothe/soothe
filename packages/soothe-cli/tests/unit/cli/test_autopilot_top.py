"""Unit tests for autopilot top CLI rendering (IG-679 / IG-686 / IG-688 / IG-694 / IG-698)."""

from __future__ import annotations

import re
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
    format_row_elapsed,
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
    goals = next(line for line in header if "Goals" in line.plain)
    assert "Steps" in goals.plain
    assert "done=1" in goals.plain
    assert "2/2 done" in goals.plain
    goals_idx = goals.plain.index("Goals")
    steps_idx = goals.plain.index("Steps")
    goals_fill = {
        str(span.style)
        for span in goals.spans
        if "█" in goals.plain[span.start : span.end] and span.start < steps_idx
    }
    steps_fill = {
        str(span.style)
        for span in goals.spans
        if "█" in goals.plain[span.start : span.end] and span.start >= steps_idx
    }
    assert goals_idx < steps_idx
    assert goals_fill == {_STYLE_ACTIVE}
    assert steps_fill == {_STYLE_ACTIVE}
    assert _STYLE_HOT not in {str(span.style) for span in goals.spans}


def test_format_elapsed_hhmmss() -> None:
    now = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
    started = now - timedelta(hours=1, minutes=2, seconds=3)
    assert format_elapsed(started.isoformat(), now=now) == "01:02:03"
    assert format_elapsed(None) == ""
    assert format_elapsed("") == ""


def test_format_elapsed_freezes_at_ended_at() -> None:
    started = datetime(2026, 8, 5, 10, 0, 0, tzinfo=UTC)
    ended = datetime(2026, 8, 5, 10, 5, 0, tzinfo=UTC)
    later = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
    assert format_elapsed(started, now=later, ended_at=ended) == "00:05:00"
    assert format_elapsed(started.isoformat(), ended_at=ended.isoformat()) == "00:05:00"


def test_render_top_completed_goal_elapsed_frozen() -> None:
    """Terminal goals must not keep ticking on refresh (mode=all)."""
    created = "2026-08-05T10:00:00+00:00"
    updated = "2026-08-05T10:05:00+00:00"
    snapshot = {
        "running": True,
        "dreaming": False,
        "loop_pool": {"active": 0, "idle": 0, "max": 4},
        "jobs": [
            {
                "id": "jobdone01",
                "status": "completed",
                "priority": 50,
                "description": "Done job",
                "created_at": created,
                "started_at": created,
                "updated_at": updated,
                "total_goals": 1,
                "completed_goals": 1,
                "active_goals": 0,
                "dag": {
                    "root_id": "jobdone01",
                    "nodes": [
                        {
                            "id": "jobdone01",
                            "status": "completed",
                            "description": "Done job",
                            "created_at": created,
                            "started_at": created,
                            "updated_at": updated,
                        }
                    ],
                    "edges": [],
                },
                "loops": [],
            }
        ],
    }
    text = _plain(snapshot, state=TopViewState(include_terminal=True))
    # Entity ids are truncated to 8 chars in the forest.
    job_line = next(ln for ln in text.splitlines() if "JOB  [jobdone0]" in ln)
    goal_line = next(ln for ln in text.splitlines() if "GOAL [jobdone0]" in ln)
    assert re.search(r"\b00:05:00\b", job_line)
    assert re.search(r"\b00:05:00\b", goal_line)


def test_format_row_elapsed_needs_start_and_non_pending_status() -> None:
    now = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
    started = (now - timedelta(minutes=5)).isoformat()
    assert format_row_elapsed("pending", None, None) == ""
    assert format_row_elapsed("pending", started, None) == ""
    assert format_row_elapsed("active", None, None) == ""
    assert format_row_elapsed("active", started, None) != ""
    assert (
        format_row_elapsed(
            "completed",
            "2026-08-05T10:00:00+00:00",
            "2026-08-05T10:05:00+00:00",
        )
        == "00:05:00"
    )


def test_render_top_pending_job_and_goal_show_no_clock() -> None:
    """Queued work must not tick — elapsed starts when the goal becomes active."""
    created = "2026-08-05T10:00:00+00:00"
    snapshot = {
        "running": True,
        "dreaming": False,
        "loop_pool": {"active": 0, "idle": 4, "max": 4},
        "jobs": [
            {
                "id": "waitjob1",
                "status": "pending",
                "priority": 50,
                "description": "Queued job",
                "created_at": created,
                "updated_at": created,
                "total_goals": 1,
                "completed_goals": 0,
                "active_goals": 0,
                "dag": {
                    "root_id": "waitjob1",
                    "nodes": [
                        {
                            "id": "waitjob1",
                            "status": "pending",
                            "description": "Queued job",
                            "created_at": created,
                            "started_at": None,
                            "updated_at": created,
                        }
                    ],
                    "edges": [],
                },
                "loops": [],
            }
        ],
    }
    text = _plain(snapshot, state=TopViewState())
    job_line = next(ln for ln in text.splitlines() if "JOB  [waitjob1]" in ln)
    goal_line = next(ln for ln in text.splitlines() if "GOAL [waitjob1]" in ln)
    assert not re.search(r"\d{2}:\d{2}:\d{2}", job_line)
    assert not re.search(r"\d{2}:\d{2}:\d{2}", goal_line)


def test_render_top_active_goal_counts_from_started_at() -> None:
    """Elapsed anchors on started_at, ignoring how long the goal sat queued."""
    # Rendering uses the live clock, so anchor the fixtures on real "now".
    now = datetime.now(UTC)
    created = (now - timedelta(hours=5)).isoformat()
    started = (now - timedelta(minutes=7)).isoformat()
    snapshot = {
        "running": True,
        "dreaming": False,
        "loop_pool": {"active": 1, "idle": 3, "max": 4},
        "jobs": [
            {
                "id": "runjob01",
                "status": "active",
                "priority": 50,
                "description": "Running job",
                "created_at": created,
                "started_at": started,
                "total_goals": 1,
                "completed_goals": 0,
                "active_goals": 1,
                "dag": {
                    "root_id": "runjob01",
                    "nodes": [
                        {
                            "id": "runjob01",
                            "status": "active",
                            "description": "Running job",
                            "created_at": created,
                            "started_at": started,
                        }
                    ],
                    "edges": [],
                },
                "loops": [],
            }
        ],
    }
    text = _plain(snapshot, state=TopViewState())
    job_line = next(ln for ln in text.splitlines() if "JOB  [runjob01]" in ln)
    goal_line = next(ln for ln in text.splitlines() if "GOAL [runjob01]" in ln)
    stamp = re.search(r"\d{2}:\d{2}:\d{2}", job_line)
    assert stamp is not None
    # Roughly 7 minutes in, not 5 hours (created_at is ignored).
    assert stamp.group(0).startswith("00:07:")
    assert re.search(r"\d{2}:\d{2}:\d{2}", goal_line)


def test_format_tokens() -> None:
    assert format_tokens(0) == "0"
    assert format_tokens(999) == "999"
    assert format_tokens(1500) == "1K"
    assert format_tokens(2_500_000) == "2M"
    assert format_tokens(None) == "0"


def test_top_view_state_defaults() -> None:
    state = TopViewState()
    assert state.steps_mode == "active"
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
    # Stats are paired: Jobs|Loops on one row (Goals alone when no steps).
    jobs_line = next(ln for ln in text.splitlines() if "Jobs" in ln and "total" in ln)
    assert "Loops" in jobs_line
    goals_line = next(ln for ln in text.splitlines() if ln.startswith("Goals"))
    assert "Loops" not in goals_line
    assert "Steps" not in goals_line
    assert "mode=active" in text
    assert "(live)" in text
    assert "q Quit" in text
    assert "refresh 2s" in text
    assert "steps=active" in text
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
    # Empty forest header: title + Jobs|Loops + Goals + flags + rule = 5
    # (+ footer 2) → max_body = height - 7; page_size = max_body - 1
    render_top_snapshot(
        {"running": True, "loop_pool": {"active": 0, "idle": 0, "max": 1}, "jobs": []},
        height=20,
        width=80,
        state=state,
    )
    assert state.page_size == max(1, 20 - 5 - 2 - 1)


def test_apply_top_key_toggles() -> None:
    state = TopViewState()
    assert state.steps_mode == "active" and state.show_loops is True
    assert state.interval == 2.0
    apply_top_key(state, "a")
    assert state.include_terminal is True
    assert state.force_refresh is True
    apply_top_key(state, "s")
    assert state.steps_mode == "all"
    apply_top_key(state, "s")
    assert state.steps_mode == "off"
    apply_top_key(state, "s")
    assert state.steps_mode == "active"
    apply_top_key(state, "l")
    assert state.show_loops is False
    state.steps_mode = "off"
    # density from compact: steps-only → full → compact → steps-only
    apply_top_key(state, "d")
    assert state.steps_mode == "all" and state.show_loops is False
    apply_top_key(state, "d")
    assert state.steps_mode == "all" and state.show_loops is True
    apply_top_key(state, "d")
    assert state.steps_mode == "off" and state.show_loops is False
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
                    "started_at": created,
                    "total_tokens_used": 12500,
                    "rail_id": "feature-dev",
                    "dag": {
                        "root_id": "a1b2c3d4",
                        "nodes": [
                            {
                                "id": "a1b2c3d4",
                                "status": "active",
                                "description": "Implement auth",
                                "created_at": created,
                                "started_at": created,
                                "steps_completed": 1,
                                "steps_total": 2,
                                "total_tokens_used": 3200,
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
                                "created_at": started,
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
        state=TopViewState(steps_mode="all", show_loops=True, interval=2.5),
    )
    text = rendered.plain
    # Patch elapsed by checking format with known now via direct helper
    assert format_elapsed(created, now=now) == "00:12:34"
    assert format_elapsed(started, now=now) == "00:03:21"
    assert "pri:50" in text
    assert "tok:12K" in text
    assert "Implement auth" in text
    assert "goals:0/2" in text
    assert "steps:1/2" in text
    assert "JOB  [a1b2c3d4]" in text
    assert "GOAL [a1b2c3d4]" in text
    # Unified order: status → metrics (name:value) → "desc" (preview at tail).
    job_line = next(ln for ln in text.splitlines() if ln.startswith("JOB  [a1b2c3d4]"))
    assert job_line.index("goals:0/2") < job_line.index('"Implement auth"')
    assert re.search(r"\d{2}:\d{2}:\d{2}  goals:0/2", job_line)
    assert job_line.index("goals:0/2") < job_line.index("tok:12K")
    assert job_line.index("tok:12K") < job_line.index("pri:50")
    assert job_line.index("pri:50") < job_line.index("rail:feature-dev")
    assert job_line.index("rail:feature-dev") < job_line.index('"Implement auth"')
    assert "rail:feature-dev" in job_line
    goal_line = next(ln for ln in text.splitlines() if "GOAL [a1b2c3d4]" in ln)
    assert goal_line.index("steps:1/2") < goal_line.index('"Implement auth"')
    assert re.search(
        r'\d{2}:\d{2}:\d{2}  steps:1/2  tok:3K  "Implement auth"',
        goal_line,
    )
    child_goal = next(ln for ln in text.splitlines() if "GOAL [e5f6aaaa]" in ln)
    # Pending goals have not started, so no clock ticks on their row.
    assert not re.search(r"\d{2}:\d{2}:\d{2}", child_goal)
    assert child_goal.endswith('pending  "Write tests"')
    # steps=all lists full StepDAG under live goals (including completed).
    assert "STEP [UZH-01]" in text
    assert "STEP [UZH-02]" in text
    assert "Add JWT" in text
    assert "→UZH-01" in text  # flat list keeps deps inline, not nested tree
    assert "Write tests" in text
    # Steps are a flat list (same indent), not a nested step tree.
    step_lines = [ln for ln in text.splitlines() if "STEP [" in ln]
    assert len(step_lines) == 2
    uzh02 = next(ln for ln in step_lines if "STEP [UZH-02]" in ln)
    assert uzh02.index('"Add JWT"') < uzh02.index("→UZH-01")
    assert "LOOP [auto…beef]" in text
    assert "seq:3" in text
    loop_line = next(ln for ln in text.splitlines() if "LOOP [auto…beef]" in ln)
    assert "seq:3" in loop_line
    assert "active" not in loop_line
    assert "pending" not in loop_line
    assert not re.search(r"\d{2}:\d{2}:\d{2}", loop_line)
    assert "refresh 2.5s" in text
    assert "bright_cyan" in rendered.markup
    assert "bright_blue" in rendered.markup  # elapsed
    assert "bright_magenta" in rendered.markup  # tok / loop seq
    assert "bright_yellow" in rendered.markup  # pri
    assert "mode=active" in text
    assert "(live)" in text
    # htop-style header aggregates from the forest (Jobs|Loops, Goals|Steps)
    assert "Jobs" in text and "active=1" in text
    assert "Goals" in text and "pending=1" in text
    assert "Loops" in text and "1/0/4" in text and "1 assigned" in text
    assert "Steps" in text and "1/2 done" in text
    jobs_line = next(ln for ln in text.splitlines() if "Jobs" in ln and "total" in ln)
    goals_line = next(ln for ln in text.splitlines() if "Goals" in ln and "total" in ln)
    assert "Loops" in jobs_line
    assert "Steps" in goals_line
    assert "up " in text  # oldest-job uptime on title line


def test_render_top_job_uses_wire_goal_totals() -> None:
    """JOB line prefers full-DAG totals even when the visible forest is filtered."""
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
                    "created_at": "2026-08-05T12:00:00+00:00",
                    "total_tokens_used": 1500,
                    "total_goals": 5,
                    "completed_goals": 2,
                    "active_goals": 1,
                    "dag": {
                        "root_id": "a1b2c3d4",
                        "nodes": [
                            {
                                "id": "a1b2c3d4",
                                "status": "active",
                                "description": "Implement auth",
                            }
                        ],
                        "edges": [],
                    },
                    "loops": [],
                }
            ],
        },
        state=TopViewState(steps_mode="off", show_loops=False),
    )
    job_line = next(ln for ln in text.splitlines() if ln.startswith("JOB  [a1b2c3d4]"))
    assert "active" in job_line
    assert '"Implement auth"' in job_line
    assert "goals:2/5" in job_line
    assert "tok:1K" in job_line
    assert "pri:50" in job_line
    assert job_line.index("goals:2/5") < job_line.index('"Implement auth"')
    goal_line = next(ln for ln in text.splitlines() if "GOAL [a1b2c3d4]" in ln)
    assert '"Implement auth"' in goal_line
    assert goal_line.index("active") < goal_line.index('"Implement auth"')


def test_render_top_hides_steps_and_loops() -> None:
    state = TopViewState(steps_mode="off", show_loops=False, interval=1.0)
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
    assert "steps:1/2" in text
    assert "UZH-01" not in text
    assert "LOOP autopilot" not in text
    assert "STEP [UZH" not in text
    assert "steps=off" in text
    assert "loops=off" in text
    assert "refresh 1s" in text
    assert "mode=active" in text
    assert "(live)" in text
    assert "Jobs" in text and "1 total" in text
    assert "Goals" in text and "active=1" in text
    assert "1/0/4" in text and "1 assigned" in text  # header counts payload loops
    # No Steps column when all steps_total are filtered from display… still counted
    # from node counters even when step nodes are hidden.
    assert "Steps" in text and "1/2 done" in text


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
    assert "pri:70" in job_line
    assert "Task: Initial C Compiler Scaffol..." in job_line
    assert "Building the compiler" not in job_line
    goal_line = next(ln for ln in text.splitlines() if "GOAL [fad4717e]" in ln)
    assert "Task: Initial C Compiler Scaffol..." in goal_line
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
    """steps=all lists completed/active/skipped STEPs under goals still in the forest."""
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
    active = _plain(snap, state=TopViewState(include_terminal=False, steps_mode="all"))
    assert "STEP [UZH-01]" in active
    assert "STEP [UZH-02]" in active
    assert "STEP [UZH-03]" in active
    assert "mode=active" in active
    assert "(live)" in active

    all_mode = _plain(snap, state=TopViewState(include_terminal=True, steps_mode="all"))
    assert "STEP [UZH-01]" in all_mode
    assert "STEP [UZH-02]" in all_mode
    assert "STEP [UZH-03]" in all_mode
    assert "mode=all" in all_mode
    assert "(live)" not in all_mode


def test_render_top_steps_active_shows_only_active_and_pending() -> None:
    snap = {
        "running": True,
        "loop_pool": {"active": 1, "idle": 0, "max": 4},
        "jobs": [
            {
                "id": "a1b2c3d4",
                "status": "active",
                "dag": {
                    "root_id": "a1b2c3d4",
                    "nodes": [
                        {
                            "id": "a1b2c3d4",
                            "status": "active",
                            "steps": {
                                "nodes": [
                                    {"id": "S-01", "status": "completed"},
                                    {"id": "S-02", "status": "active"},
                                    {"id": "S-03", "status": "pending"},
                                    {"id": "S-04", "status": "failed"},
                                ]
                            },
                        }
                    ],
                    "edges": [],
                },
                "loops": [],
            }
        ],
    }

    text = _plain(snap, state=TopViewState(steps_mode="active"))

    assert "steps=active" in text
    assert "STEP [S-02]" in text
    assert "STEP [S-03]" in text
    assert "STEP [S-01]" not in text
    assert "STEP [S-04]" not in text


def test_render_top_active_goal_all_completed_steps_still_listed() -> None:
    """Live goal with steps N/N must still show STEP rows when steps=all."""
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
        state=TopViewState(include_terminal=False, steps_mode="all", show_loops=True),
    )
    assert "steps:2/2" in text
    assert "STEP [JNC-01] completed" in text
    assert "STEP [JNC-02] completed" in text
    assert "LOOP [auto…beef]" in text


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
        state=TopViewState(steps_mode="all", show_loops=True, interval=1.0),
    )
    assert "JOB  [jobjobj1] active" in text
    assert "GOAL [jobjobj1] active" in text
    assert "STEP [S-01] active" in text
    assert "LOOP [auto…beef]" in text
    loop_line = next(ln for ln in text.splitlines() if "LOOP [auto…beef]" in ln)
    assert "seq:1" in loop_line
    assert "active" not in loop_line
    assert "pending" not in loop_line


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
