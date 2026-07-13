"""Loop selector column formatting for polished /resume table."""

from __future__ import annotations

from soothe_cli.tui.model_config import load_loop_config
from soothe_cli.tui.widgets.loop_selector import (
    _format_column_value,
    _is_active_loop,
    _sort_loops,
    _visible_column_keys,
)


def test_format_column_value_topic_falls_back_to_prompt() -> None:
    loop = {
        "loop_id": "loop-abc123456789",
        "messages": 4,
        "updated": "2026-06-30T09:00:45+00:00",
        "prompt": "Refactor daemon session handling",
    }
    assert _format_column_value(loop, "topic") == "Refactor daemon session handling"


def test_format_column_value_topic_prefers_generated_label() -> None:
    loop = {
        "loop_id": "loop-abc123456789",
        "messages": 12,
        "updated": "2026-06-30T09:00:45+00:00",
        "prompt": "Long original user goal text here",
        "topic": "Daemon session refactor",
    }
    assert _format_column_value(loop, "topic") == "Daemon session refactor"


def test_format_column_value_topic_marks_live_loop() -> None:
    loop = {
        "loop_id": "loop-abc123456789",
        "live": True,
        "topic": "Running task",
    }
    assert _format_column_value(loop, "topic") == "● Running task"


def test_format_column_value_topic_marks_running_loop() -> None:
    loop = {
        "loop_id": "loop-abc123456789",
        "status": "running",
        "topic": "Interrupted task",
    }
    assert _format_column_value(loop, "topic") == "◐ Interrupted task"


def test_sort_loops_promotes_active_rows() -> None:
    loops = [
        {"loop_id": "idle", "status": "idle", "updated_at": "2026-07-11T12:00:00+00:00"},
        {"loop_id": "live", "live": True, "updated_at": "2026-07-11T10:00:00+00:00"},
        {
            "loop_id": "running",
            "status": "running",
            "updated_at": "2026-07-11T11:00:00+00:00",
        },
    ]
    ordered = _sort_loops(loops, sort_key="updated_at")
    assert [loop["loop_id"] for loop in ordered] == ["running", "live", "idle"]


def test_sort_loops_uses_updated_timestamp_for_recency_descending() -> None:
    loops = [
        {
            "loop_id": "older",
            "status": "idle",
            "created": "2026-07-11T01:00:00+00:00",
            "updated": "2026-07-11T02:00:00+00:00",
        },
        {
            "loop_id": "latest",
            "status": "idle",
            "created": "2026-07-10T01:00:00+00:00",
            "updated": "2026-07-11T09:00:00+00:00",
        },
    ]
    ordered = _sort_loops(loops, sort_key="updated_at")
    assert [loop["loop_id"] for loop in ordered] == ["latest", "older"]


def test_is_active_loop_true_for_live_or_running() -> None:
    assert _is_active_loop({"live": True, "status": "idle"}) is True
    assert _is_active_loop({"status": "running"}) is True
    assert _is_active_loop({"status": "idle"}) is False


def test_format_column_value_shows_only_resume_columns() -> None:
    loop = {
        "loop_id": "019f1b8a838570f19248402013b8b036",
        "messages": 3,
        "updated": "2026-06-30T09:00:45+00:00",
        "topic": "Auth bug fix",
    }
    assert _format_column_value(loop, "loop_id") == "019f1b8a83...b036"
    assert _format_column_value(loop, "topic") == "Auth bug fix"


def test_default_resume_columns_topic_updated_loop_id_without_messages() -> None:
    cfg = load_loop_config()
    assert _visible_column_keys(cfg.columns) == ["topic", "updated_at", "loop_id"]
