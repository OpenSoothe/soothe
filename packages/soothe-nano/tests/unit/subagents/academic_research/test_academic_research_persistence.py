"""Tests for academic_research report persistence."""

from __future__ import annotations

from pathlib import Path

from soothe_nano.subagents.academic_research.display_summary import derive_report_title
from soothe_nano.subagents.academic_research.persistence import (
    format_saved_report_answer,
    save_academic_research_report,
    slugify_report_title,
)


def test_derive_report_title_prefers_non_scope_heading() -> None:
    report = "## Scope\n\nAcademic only.\n\n## Key Findings\n\nAttention improves recall."
    assert derive_report_title(report, "attention") == "Key Findings"


def test_slugify_report_title() -> None:
    assert slugify_report_title("Transformer Attention (2024)") == "transformer-attention-2024"


def test_save_academic_research_report_writes_workspace_relative_file(tmp_path: Path) -> None:
    from soothe_nano.workspace.workspace_runtime import set_workspace_context

    token = set_workspace_context(workspace=tmp_path, virtual_mode=False)
    try:
        report = "## Scope\n\nAcademic only.\n\n## Key Findings\n\nFinding one about attention."
        saved = save_academic_research_report(report, topic="attention papers")
        assert saved is not None
        assert saved.host_path.exists()
        assert saved.host_path.read_text(encoding="utf-8") == report
        assert saved.display_path.startswith(".soothe/agents/academic_research/")
        assert saved.display_path.endswith(".md")
        assert "key-findings" in saved.host_path.name
        assert "Finding one" in saved.brief_summary
    finally:
        from soothe_nano.workspace.workspace_runtime import reset_workspace_context

        reset_workspace_context(token)


def test_format_saved_report_answer() -> None:
    from soothe_nano.subagents.academic_research.persistence import SavedAcademicResearchReport

    saved = SavedAcademicResearchReport(
        host_path=Path("/tmp/example.md"),
        display_path=".soothe/agents/academic_research/example.md",
        brief_summary="Attention improves recall.",
    )
    answer = format_saved_report_answer(saved)
    assert "## Summary" in answer
    assert "Attention improves recall." in answer
    assert "`.soothe/agents/academic_research/example.md`" in answer
