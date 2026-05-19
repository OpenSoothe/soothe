"""Unit tests for CognitionStepMessage tool row aggregation (IG-402)."""

from __future__ import annotations

from time import time
from unittest.mock import patch

import pytest

from soothe_cli.tui import theme as theme_mod
from soothe_cli.tui.preview_limits import (
    STEP_CARD_SHOW_TOOL_ROW_DETAILS,
    STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD,
)
from soothe_cli.tui.widgets.messages import CognitionStepMessage, ToolCallMessage


def test_snapshot_apply_roundtrip() -> None:
    w = CognitionStepMessage("s1", "Do work", id="st1")
    w.add_tool_call("c1", "grep", {"pattern": "x"})
    w.set_tool_success("c1", "matches", duration_ms=10)
    snap = w.snapshot_tool_rows()
    w2 = CognitionStepMessage("s1", "Do work", id="st2")
    w2.apply_tool_rows_snapshot(snap)
    assert w2.has_tool_call_row("c1")
    assert w2._row_index["c1"].phase == "success"  # noqa: SLF001


def test_mark_unfinished_tools_skipped() -> None:
    w = CognitionStepMessage("s2", "Partial", id="st2")
    w.add_tool_call("u1", "read_file", {"file_path": "x.txt"})
    w.mark_unfinished_tools_skipped()
    assert w._row_index["u1"].phase == "skipped"  # noqa: SLF001


def test_stats_title_suffix_counts_by_display_name() -> None:
    w = CognitionStepMessage("s3", "Work", id="st3")
    w.add_tool_call("a", "grep", {"pattern": "p1"})
    w.add_tool_call("b", "grep", {"pattern": "p2"})
    w.add_tool_call("c", "ls", {"path": "."})
    suffix = w._stats_title_suffix()
    assert "Grep(2)" in suffix
    assert "ListFiles(1)" in suffix or "List(1)" in suffix


def test_running_status_line_includes_tool_call_stats_suffix() -> None:
    """Running step status shows per-tool counts (IG-402)."""
    w = CognitionStepMessage("s-run", "Work", id="st-run-stats")
    w.add_tool_call("a", "read_file", {"file_path": "/x.md"})
    w.add_tool_call("b", "glob_file_search", {"glob_pattern": "*.md"})
    w._status = "running"  # noqa: SLF001
    w._spinner_position = 0  # noqa: SLF001
    w._start_time = time() - 2  # noqa: SLF001
    captured: list[str] = []

    class _FakeStatus:
        def update(self, content: object) -> None:
            from textual.content import Content

            if isinstance(content, Content):
                captured.append(content.plain)
            else:
                captured.append(str(content))

    w._status_widget = _FakeStatus()  # noqa: SLF001
    suffix = w._stats_title_suffix()
    with (
        patch("soothe_cli.tui.widgets.messages._is_widget_animation_visible", return_value=True),
        patch.object(theme_mod, "get_theme_colors", return_value=theme_mod.DARK_COLORS),
    ):
        w._update_running_animation()
    assert len(captured) == 1
    line = captured[0]
    assert "Running..." in line
    assert suffix in line
    assert suffix.strip().startswith("·")


def test_step_header_has_no_tool_count_suffix() -> None:
    w = CognitionStepMessage("s-hdr", "Read RFCs", id="st-hdr")
    w.add_tool_call("a", "grep", {"pattern": "x"})
    w.add_tool_call("b", "grep", {"pattern": "y"})
    suffix = w._stats_title_suffix()
    assert "Grep(2)" in suffix
    assert "Grep(2)" not in w._step_header_content().plain


def test_format_tool_call_row_smoke() -> None:
    from soothe_cli.tui.tool_display import format_tool_call_row

    c = format_tool_call_row("grep", {"pattern": "TODO"}, phase="pending")
    assert "grep" in c.plain.lower() or "Grep" in c.plain


def test_format_tool_call_row_branch_glyph_hollow_running_no_braille_spinner() -> None:
    """Step-card parity: running uses ○ only, not Braille frames."""
    from soothe_cli.tui.config import get_glyphs
    from soothe_cli.tui.tool_display import format_tool_call_row

    g = get_glyphs()
    c = format_tool_call_row(
        "grep",
        {"pattern": "x"},
        phase="running",
        branch_glyph=g.circle_empty,
        running_elapsed_secs=1.0,
    )
    plain = c.plain
    assert g.circle_empty in plain
    for frame in g.spinner_frames:
        assert frame not in plain


def test_step_auto_collapses_when_body_lines_exceed_threshold() -> None:
    w = CognitionStepMessage("s-auto", "Work", id="st-auto")
    n = STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD + 1
    for i in range(n):
        w.append_subagent_activity(f"meta {i}")
    assert w._card_collapsed  # noqa: SLF001


def test_step_card_hides_tool_row_details_by_default() -> None:
    """Stats-only mode: no per-tool CLI rows in the card body."""
    assert STEP_CARD_SHOW_TOOL_ROW_DETAILS is False
    w = CognitionStepMessage("s-hide", "Work", id="st-hide")
    w.add_tool_call("c1", "grep", {"pattern": "x"})
    w.add_tool_call("c2", "read_file", {"file_path": "/a.md"})
    w._tools_widget = type("W", (), {"display": True, "update": lambda *_a, **_k: None})()  # noqa: SLF001
    w._refresh_tools_display(force=True)
    assert w._tools_widget.display is False  # noqa: SLF001
    assert "Grep(1)" in w._stats_title_suffix()


def test_step_respects_user_expand_after_auto_collapse() -> None:
    w = CognitionStepMessage("s-user", "Work", id="st-user")
    for i in range(STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD + 1):
        w.append_subagent_activity(f"meta {i}")
    assert w._card_collapsed  # noqa: SLF001
    w.toggle_collapse()
    assert not w._card_collapsed  # noqa: SLF001
    w.append_subagent_activity("extra meta")
    assert not w._card_collapsed  # noqa: SLF001


def test_step_auto_folds_tool_list_when_rows_exceed_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool-row preview folds as rows stream in when detail rows are enabled."""
    monkeypatch.setattr(
        "soothe_cli.tui.widgets.messages.STEP_CARD_SHOW_TOOL_ROW_DETAILS",
        True,
    )
    w = CognitionStepMessage("s-fold", "Work", id="st-fold")
    for i in range(STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD + 1):
        w.add_tool_call(f"c{i}", "grep", {"pattern": str(i)})
    assert w._tools_body_collapsed  # noqa: SLF001


def test_step_tool_list_fold_respects_user_expand(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "soothe_cli.tui.widgets.messages.STEP_CARD_SHOW_TOOL_ROW_DETAILS",
        True,
    )
    w = CognitionStepMessage("s-tlu", "Work", id="st-tlu")
    for i in range(STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD):
        w.add_tool_call(f"c{i}", "grep", {"pattern": str(i)})
    w.add_tool_call("c3", "grep", {"pattern": "3"})
    assert w._tools_body_collapsed  # noqa: SLF001
    w.toggle_collapse()
    assert not w._card_collapsed  # noqa: SLF001
    w._tools_body_collapsed = False
    w._step_tool_list_user_expanded = True
    w.add_tool_call("extra", "ls", {"path": "."})
    assert not w._tools_body_collapsed  # noqa: SLF001


def test_task_tool_auto_folds_activity_when_over_preview_threshold() -> None:
    w = ToolCallMessage("task", {"description": "d"}, id="tsk-fold")
    for i in range(STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD):
        w.append_subagent_activity(f"meta {i}")
    w.append_subagent_activity("meta 3")
    assert w._tools_body_collapsed  # noqa: SLF001


def test_task_auto_collapses_when_activity_exceeds_threshold() -> None:
    w = ToolCallMessage("task", {}, id="tsk-auto")
    for i in range(STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD + 1):
        w.append_subagent_activity(f"meta {i}")
    assert w._card_collapsed  # noqa: SLF001


def test_format_tool_call_row_branch_glyph_filled_on_success() -> None:
    from soothe_cli.tui.config import get_glyphs
    from soothe_cli.tui.tool_display import format_tool_call_row

    g = get_glyphs()
    c = format_tool_call_row(
        "grep",
        {"pattern": "x"},
        phase="success",
        output="ok",
        duration_ms=10,
        branch_glyph=g.circle_filled,
    )
    assert g.circle_filled in c.plain
