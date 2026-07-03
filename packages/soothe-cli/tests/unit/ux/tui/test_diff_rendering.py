"""Tests for unified diff row alignment in TUI previews."""

from __future__ import annotations

from soothe_cli.tui.widgets.diff import format_diff_row_plain, split_unified_diff_body_line


def test_split_unified_diff_body_line_preserves_indented_content() -> None:
    """Indented code after the diff marker must not lose leading spaces."""
    marker, content = split_unified_diff_body_line("+                        cron_job_id=job.id,")
    assert marker == "+"
    assert content.startswith("                        cron")


def test_added_and_context_rows_align_code_columns() -> None:
    """Added/removed rows must start code at the same column as context rows."""
    width = 3
    content = "                        cron_job_id=job.id,"
    context_row = format_diff_row_plain(" ", content, line_num=272, width=width)
    added_row = format_diff_row_plain("+", content, line_num=275, width=width)

    assert context_row.endswith(content)
    assert added_row.endswith(content)
    assert context_row.index(content) == added_row.index(content)


def test_removed_rows_align_with_context() -> None:
    """Removed rows share the same code column as context rows."""
    width = 3
    content = "from typing import TYPE_CHECKING"
    context_row = format_diff_row_plain(" ", content, line_num=11, width=width)
    removed_row = format_diff_row_plain("-", content, line_num=12, width=width)

    assert context_row.index(content) == removed_row.index(content)
