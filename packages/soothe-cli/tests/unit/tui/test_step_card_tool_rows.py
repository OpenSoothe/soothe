"""Unit tests for CognitionStepMessage tool row aggregation (IG-402)."""

from __future__ import annotations

from soothe_cli.tui.widgets.messages import CognitionStepMessage


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
