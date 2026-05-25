"""Tests for Tacitus: protocol, public sources, router, and factory."""

from __future__ import annotations

import pytest

from soothe.subagents.tacitus import (
    GatherContext,
    SourceResult,
    TacitusConfig,
)
from soothe.subagents.tacitus.router import PublicSemanticRouter


class TestSourceResult:
    def test_minimal_creation(self) -> None:
        r = SourceResult(content="hello", source_ref="test", source_name="mock")
        assert r.content == "hello"
        assert r.confidence == 1.0


class TestTacitusConfig:
    def test_defaults(self) -> None:
        cfg = TacitusConfig()
        assert cfg.max_loops == 3
        assert cfg.effort == "normal"
        assert cfg.llm_role == "fast"
        assert cfg.synthesis_role == "think"
        assert "public" in cfg.capability_profiles
        assert "web_search" in cfg.enabled_capabilities

    def test_validation_bounds(self) -> None:
        with pytest.raises(ValueError):
            TacitusConfig(max_loops=0)


class MockPublicSource:
    """Minimal PublicInformationSource for router tests."""

    def __init__(
        self,
        name: str,
        source_type: str,
        capability_id: str,
        description: str = "Mock public source for testing.",
    ) -> None:
        self._name = name
        self._source_type = source_type
        self._capability_id = capability_id
        self._description = description

    @property
    def name(self) -> str:
        return self._name

    @property
    def capability_id(self) -> str:
        return self._capability_id

    @property
    def source_type(self) -> str:
        return self._source_type

    @property
    def capability_description(self) -> str:
        return self._description

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        return [
            SourceResult(
                content=f"mock:{query}",
                source_ref=self._name,
                source_name=self._name,
            )
        ]


class TestPublicSemanticRouter:
    def test_selects_sources_for_public_domain(self) -> None:
        sources = [
            MockPublicSource("web", "web", "web_search", "Web search."),
            MockPublicSource("acad", "academic", "academic_search", "Academic papers."),
            MockPublicSource("crawl", "url", "url_crawl", "URL crawl."),
        ]
        router = PublicSemanticRouter(sources, TacitusConfig(max_sources_per_query=2))
        selected = router.select("transformer architecture papers", domain="public")
        assert len(selected) >= 1
        assert len(selected) <= 2

    def test_web_domain_excludes_academic_only_profile(self) -> None:
        sources = [
            MockPublicSource("web", "web", "web_search"),
            MockPublicSource("acad", "academic", "academic_search"),
        ]
        router = PublicSemanticRouter(sources)
        selected = router.select("query", domain="web")
        ids = {s.capability_id for s in selected}
        assert "web_search" in ids
        assert "academic_search" not in ids

    def test_url_fast_path_includes_crawl(self) -> None:
        sources = [
            MockPublicSource("web", "web", "web_search"),
            MockPublicSource("crawl", "url", "url_crawl", "URL crawl."),
        ]
        router = PublicSemanticRouter(sources, TacitusConfig(max_sources_per_query=3))
        selected = router.select(
            "read https://example.com/doc",
            domain="public",
        )
        assert any(s.capability_id == "url_crawl" for s in selected)


class TestTacitusSubagent:
    def test_factory(self) -> None:
        from soothe.subagents.tacitus import create_tacitus_subagent

        assert callable(create_tacitus_subagent)

    def test_plugin(self) -> None:
        from soothe.subagents.tacitus import TacitusPlugin

        assert TacitusPlugin is not None
