"""Tests for unified diff row alignment in TUI previews."""

from __future__ import annotations

from soothe_cli.tui.widgets.diff import split_unified_diff_body_line


def test_split_unified_diff_body_line_preserves_indented_content() -> None:
    """Indented code after the diff marker must not lose leading spaces."""
    marker, content = split_unified_diff_body_line("+                        cron_job_id=job.id,")
    assert marker == "+"
    assert content.startswith("                        cron")
