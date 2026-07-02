"""Loop selector column formatting for polished /resume table."""

from __future__ import annotations

from soothe_cli.tui.model_config import load_loop_config
from soothe_cli.tui.widgets.loop_selector import (
    _format_column_value,
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


def test_format_column_value_shows_only_resume_columns() -> None:
    loop = {
        "loop_id": "019f1b8a838570f19248402013b8b036",
        "messages": 3,
        "updated": "2026-06-30T09:00:45+00:00",
        "topic": "Auth bug fix",
    }
    assert "019f1b8a" in _format_column_value(loop, "loop_id")
    assert _format_column_value(loop, "topic") == "Auth bug fix"


def test_default_resume_columns_topic_updated_loop_id_without_messages() -> None:
    cfg = load_loop_config()
    assert _visible_column_keys(cfg.columns) == ["topic", "updated_at", "loop_id"]
