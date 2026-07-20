"""Tests for deep_research display summary."""

from __future__ import annotations

from soothe_nano.subagents.deep_research.display_summary import (
    deep_research_brief_summary_for_display,
)


def test_deep_research_brief_summary_skips_scope() -> None:
    report = "## Scope\n\nPublic web only.\n\n## Key Findings\n\nFinding one."
    assert deep_research_brief_summary_for_display(report) == "Finding one."


def test_deep_research_brief_summary_prefers_key_findings() -> None:
    report = "## Scope\n\nPublic web only.\n\n## Key Findings\n\nFinding one about the market."
    assert "Finding one about the market." in deep_research_brief_summary_for_display(report)
