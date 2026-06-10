"""Tests for Claude Code one-line display summary."""

from soothe.foundation.core.agent.claude_display_summary import claude_text_summary_for_display


def test_prefers_markdown_heading() -> None:
    body = "Some intro\n\n## Count results\n\nThere are 88 files."
    assert claude_text_summary_for_display(body) == "Count results"


def test_first_line_when_no_heading() -> None:
    body = "Here is the answer in one line."
    assert claude_text_summary_for_display(body) == "Here is the answer in one line."


def test_truncates_long_heading() -> None:
    long_h = "# " + "x" * 200
    out = claude_text_summary_for_display(long_h + "\nmore")
    assert len(out) == 160
    assert out.endswith("…")
