"""Tests for deep_research report persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe_nano.subagents.deep_research.display_summary import derive_report_title
from soothe_nano.subagents.deep_research.persistence import (
    format_saved_report_answer,
    save_deep_research_report,
    slugify_report_title,
)


def test_derive_report_title_prefers_non_scope_heading() -> None:
    report = "## Scope\n\nPublic web only.\n\n## Executive Summary\n\nWidgets are growing fast."
    assert derive_report_title(report, "widgets") == "Executive Summary"


def test_slugify_report_title() -> None:
    assert slugify_report_title("LangGraph vs CrewAI (2026)") == "langgraph-vs-crewai-2026"


def test_save_deep_research_report_writes_workspace_relative_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from soothe_nano.workspace.workspace_runtime import set_workspace_context

    token = set_workspace_context(workspace=tmp_path, virtual_mode=False)
    try:
        report = "## Scope\n\nPublic web only.\n\n## Key Findings\n\nFinding one about widgets."
        saved = save_deep_research_report(report, topic="widget market")
        assert saved is not None
        assert saved.host_path.exists()
        assert saved.host_path.read_text(encoding="utf-8") == report
        assert saved.display_path.startswith(".soothe/agents/deep_research/")
        assert saved.display_path.endswith(".md")
        assert "key-findings" in saved.host_path.name
        assert "Finding one" in saved.brief_summary
    finally:
        from soothe_nano.workspace.workspace_runtime import reset_workspace_context

        reset_workspace_context(token)


def test_format_saved_report_answer() -> None:
    from soothe_nano.subagents.deep_research.persistence import SavedDeepResearchReport

    saved = SavedDeepResearchReport(
        host_path=Path("/tmp/example.md"),
        display_path=".soothe/agents/deep_research/example.md",
        brief_summary="Widgets are growing fast.",
    )
    answer = format_saved_report_answer(saved)
    assert "## Summary" in answer
    assert "Widgets are growing fast." in answer
    assert "`.soothe/agents/deep_research/example.md`" in answer
