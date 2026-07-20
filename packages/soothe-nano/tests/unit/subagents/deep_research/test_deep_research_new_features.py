"""Unit tests for deep_research config and report classifier."""

from __future__ import annotations

from soothe_nano.subagents.deep_research.protocol import SCOPE_BANNER, DeepResearchConfig
from soothe_nano.subagents.deep_research.report_classifier import fallback_classification


class TestDeepResearchConfig:
    def test_default_effort_normal(self) -> None:
        assert DeepResearchConfig().effort == "normal"

    def test_save_reports_disabled_by_default(self) -> None:
        assert DeepResearchConfig().save_reports is False

    def test_scope_banner_text(self) -> None:
        assert "public web" in SCOPE_BANNER.lower()
        assert "local repository" in SCOPE_BANNER.lower()


class TestReportClassifierFallback:
    def test_comparison_scenario(self) -> None:
        result = fallback_classification("Redis vs Memcached for caching")
        assert result.scenario == "comparison"

    def test_general_fallback(self) -> None:
        result = fallback_classification("agent memory survey")
        assert result.scenario == "general_research"
