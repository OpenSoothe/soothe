"""Tests for deep_research protocol and plugin surface."""

from __future__ import annotations

import pytest

from soothe_nano.subagents.deep_research import DeepResearchConfig, GatherContext, SourceResult


class TestSourceResult:
    def test_minimal_creation(self) -> None:
        r = SourceResult(content="hello", source_ref="test", source_name="mock")
        assert r.content == "hello"
        assert r.confidence == 1.0


class TestDeepResearchConfig:
    def test_defaults(self) -> None:
        cfg = DeepResearchConfig()
        assert cfg.effort == "normal"
        assert cfg.llm_role == "fast"
        assert cfg.synthesis_role == "fast"
        assert cfg.enable_early_termination is True

    def test_validation_bounds(self) -> None:
        with pytest.raises(ValueError):
            DeepResearchConfig(source_timeout_sec=0.5)


class TestDeepResearchSubagent:
    def test_factory(self) -> None:
        from soothe_nano.subagents.deep_research import create_deep_research_subagent

        assert callable(create_deep_research_subagent)

    def test_plugin(self) -> None:
        from soothe_nano.subagents.deep_research import DeepResearchPlugin

        assert DeepResearchPlugin is not None

    def test_gather_context(self) -> None:
        ctx = GatherContext(topic="test topic")
        assert ctx.topic == "test topic"
