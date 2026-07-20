"""Tests for browser subagent one-line display summary (IG-344)."""

from soothe_nano.subagents.browser_use.display_summary import browser_use_result_summary_for_display


def test_first_non_empty_line() -> None:
    raw = "\n\n**Title:** Example\n**URL:** https://x.test"
    assert browser_use_result_summary_for_display(raw) == "**Title:** Example"
