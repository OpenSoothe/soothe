"""IG-664: step card Todo/Tools sections and compact title meta."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from soothe_cli.tui import theme
from soothe_cli.tui.widgets.messages import CognitionStepMessage
from soothe_cli.tui.widgets.messages.cognition_step_activity import (
    compact_step_title_meta,
    normalize_todo_items,
)


def _mock_theme_colors() -> MagicMock:
    colors = MagicMock()
    colors.warning = "#ff0000"
    colors.cognition = "#00ff00"
    colors.foreground = "#000000"
    colors.muted = "#888888"
    colors.error = "#ff0000"
    colors.primary = "#0000ff"
    colors.success = "#00ff00"
    return colors


def _plain(content: object) -> str:
    if hasattr(content, "plain"):
        return content.plain
    return str(content)


def test_compact_step_title_meta_counts_and_tokens() -> None:
    meta = compact_step_title_meta(
        elapsed_secs=45,
        tool_count=12,
        task_count=1,
        input_tokens=8100,
        output_tokens=2000,
        format_token=lambda n: f"{n / 1000:.1f}K" if n >= 1000 else str(n),
    )
    assert meta == " · 45s · 12/1 · ↑8.1K ↓2.0K"


def test_compact_step_title_meta_retry() -> None:
    meta = compact_step_title_meta(
        elapsed_secs=12,
        tool_count=0,
        task_count=0,
        retry_attempt=1,
        max_retry_attempts=3,
    )
    assert meta == " · 12s · ↻1/3"


def test_normalize_todo_items() -> None:
    assert normalize_todo_items(
        [
            {"content": "Survey docs", "status": "in_progress"},
            {"text": "Fix errors", "status": "pending"},
            "plain item",
            {"content": "  "},
        ]
    ) == [
        {"content": "Survey docs", "status": "in_progress"},
        {"content": "Fix errors", "status": "pending"},
        {"content": "plain item", "status": "pending"},
    ]


def test_activity_tree_todo_above_tools() -> None:
    card = CognitionStepMessage("TD-01", "Scan Frontend and Backend", id="stp-todo")
    card._status = "running"
    card.set_todos(
        [
            {"content": "Survey frontend tree", "status": "in_progress"},
            {"content": "Survey backend tree", "status": "pending"},
        ]
    )
    card.add_tool_call(
        "TD_01:s:list_files:0",
        "list_files",
        {"path": "~/Workspace/Longan"},
    )
    text = _plain(card._step_task_activity_content())
    assert "TODO" in text
    assert "TOOLS" in text
    assert "Survey frontend tree" in text
    assert "ListFiles" in text
    todo_idx = text.index("TODO")
    tools_idx = text.index("TOOLS")
    assert todo_idx < tools_idx
    assert tools_idx < text.index("ListFiles")


def test_write_todos_json_string_args_populate_todo_section() -> None:
    """Streaming may deliver todos as a JSON string inside args."""
    import json

    card = CognitionStepMessage("TD-06", "Plan work", id="stp-wt-json")
    payload = [
        {"content": "A", "status": "pending"},
        {"content": "B", "status": "in_progress"},
    ]
    card.add_tool_call(
        "TD_06:s:write_todos:0",
        "WriteTodos",
        {"todos": json.dumps(payload)},
    )
    text = _plain(card._step_task_activity_content())
    assert any(ln.strip().endswith("TODO") and "Write" not in ln for ln in text.split("\n"))
    assert "A" in text and "B" in text


def test_write_todos_tool_args_populate_todo_section() -> None:
    """Todo list comes from write_todos wire args (daemon does not emit todos)."""
    card = CognitionStepMessage("TD-04", "Plan work", id="stp-wt-args")
    card.add_tool_call(
        "TD_04:s:write_todos:0",
        "write_todos",
        {
            "todos": [
                {"content": "Survey frontend tree", "status": "in_progress"},
                {"content": "Survey backend tree", "status": "pending"},
            ]
        },
    )
    card.add_tool_call("TD_04:s:grep:0", "grep", {"pattern": "x"})
    text = _plain(card._step_task_activity_content())
    assert "TODO" in text
    assert "Survey frontend tree" in text
    assert "Survey backend tree" in text
    assert "TOOLS" in text
    assert "Grep" in text
    assert "write_todos" not in text.lower()


def test_write_todos_arg_updates_refresh_todo_section() -> None:
    card = CognitionStepMessage("TD-05", "Plan work", id="stp-wt-upd")
    card.add_tool_call("TD_05:s:write_todos:0", "write_todos", {"todos": []})
    assert card._todos == []
    card.update_tool_args(
        "TD_05:s:write_todos:0",
        {"todos": [{"content": "Ship it", "status": "completed"}]},
    )
    text = _plain(card._step_task_activity_content())
    assert any(ln.strip().endswith("TODO") and "Write" not in ln for ln in text.split("\n"))
    assert "Ship it" in text
    assert "writetodos" not in text.lower().replace(" ", "")


def test_write_todos_hidden_from_tools_when_todo_section_live() -> None:
    card = CognitionStepMessage("TD-02", "Plan work", id="stp-hide-wt")
    card.set_todos([{"content": "Do work", "status": "pending"}])
    card.add_tool_call(
        "TD_02:s:write_todos:0",
        "write_todos",
        {"todos": [{"content": "Do work", "status": "pending"}]},
    )
    card.add_tool_call("TD_02:s:grep:0", "grep", {"pattern": "x"})
    text = _plain(card._step_task_activity_content())
    assert "TODO" in text
    assert "Do work" in text
    assert "write_todos" not in text.lower()
    assert "Grep" in text


def test_title_keeps_full_description_with_compact_meta() -> None:
    long_desc = "Scan Frontend and Backend without truncating this brief"
    card = CognitionStepMessage("TD-03", long_desc, id="stp-title")
    card._status = "running"
    card._start_time = 0.0
    card.add_tool_call("TD_03:s:grep:0", "grep", {})
    card.add_tool_call(
        "TD_03:s:task:0",
        "task",
        {"subagent_type": "deep_research", "description": "scan"},
        is_task_row=True,
    )
    card.record_token_usage(1200, 340)
    mock_header = MagicMock()
    card._header_widget = mock_header
    with patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()):
        card._refresh_header_title()
    text = _plain(mock_header.update.call_args[0][0])
    assert long_desc in text
    assert "1/1" in text
    assert "↑1.2K" in text
    assert "↓340" in text
