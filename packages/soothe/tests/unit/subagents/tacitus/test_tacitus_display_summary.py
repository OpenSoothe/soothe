"""Tests for Tacitus one-line display summary."""

from soothe.subagents.tacitus.display_summary import tacitus_answer_summary_for_display


def test_first_paragraph_collapsed() -> None:
    ans = "RFC-619 describes Tacitus.\n\nMore detail in section 2."
    assert tacitus_answer_summary_for_display(ans) == "RFC-619 describes Tacitus."
