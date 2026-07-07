"""Tests for deep_research display summary."""

from __future__ import annotations

from soothe.subagents.deep_research.display_summary import deep_research_report_summary_for_display


def test_deep_research_report_summary_for_display() -> None:
    report = "## Scope\n\nPublic web only.\n\n## Key Findings\n\nFinding one."
    assert deep_research_report_summary_for_display(report) == "## Scope"
