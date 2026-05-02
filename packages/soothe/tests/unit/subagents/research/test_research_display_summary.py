"""Tests for research subagent one-line display summary (IG-344)."""

from soothe.subagents.research.display_summary import research_answer_summary_for_display


def test_first_paragraph_collapsed() -> None:
    ans = "RFC-613 describes the explore agent.\n\nMore detail in section 2."
    assert research_answer_summary_for_display(ans) == "RFC-613 describes the explore agent."
