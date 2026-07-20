"""Unit tests for academic_research config and report classifier."""

from __future__ import annotations

from soothe_nano.subagents.academic_research.protocol import SCOPE_BANNER, AcademicResearchConfig
from soothe_nano.subagents.academic_research.report_classifier import fallback_classification


class TestAcademicResearchConfig:
    def test_default_effort_normal(self) -> None:
        assert AcademicResearchConfig().effort == "normal"

    def test_save_reports_disabled_by_default(self) -> None:
        assert AcademicResearchConfig().save_reports is False

    def test_scope_banner_text(self) -> None:
        assert "academic literature" in SCOPE_BANNER.lower()
        assert "local repository" in SCOPE_BANNER.lower()


class TestAcademicReportClassifierFallback:
    def test_literature_review_scenario(self) -> None:
        result = fallback_classification("literature review on transformer memory")
        assert result.scenario == "literature_review"

    def test_paper_comparison_scenario(self) -> None:
        result = fallback_classification("BERT vs GPT for embeddings")
        assert result.scenario == "paper_comparison"

    def test_general_academic_fallback(self) -> None:
        result = fallback_classification("recent advances in agent planning")
        assert result.scenario == "general_academic"
