"""Tests for the Inquiry Engine: protocol, sources, router, and engine."""

from __future__ import annotations

import pytest

from soothe.inquiry.protocol import (
    GatherContext,
    InformationSource,
    InquiryConfig,
    SourceResult,
)

# ---------------------------------------------------------------------------
# Protocol and model tests
# ---------------------------------------------------------------------------


class TestSourceResult:
    def test_minimal_creation(self) -> None:
        r = SourceResult(content="hello", source_ref="test", source_name="mock")
        assert r.content == "hello"
        assert r.confidence == 1.0
        assert r.metadata == {}

    def test_with_metadata(self) -> None:
        r = SourceResult(
            content="data",
            source_ref="/path/file.py",
            source_name="filesystem",
            confidence=0.9,
            metadata={"line": 42},
        )
        assert r.metadata["line"] == 42
        assert r.confidence == 0.9


class TestGatherContext:
    def test_defaults(self) -> None:
        ctx = GatherContext(topic="test")
        assert ctx.topic == "test"
        assert ctx.iteration == 0
        assert ctx.existing_summaries == []
        assert ctx.knowledge_gaps == []

    def test_with_state(self) -> None:
        ctx = GatherContext(
            topic="auth security",
            existing_summaries=["summary1"],
            knowledge_gaps=["MFA patterns"],
            iteration=2,
        )
        assert ctx.iteration == 2
        assert len(ctx.knowledge_gaps) == 1


class TestInquiryConfig:
    def test_defaults(self) -> None:
        cfg = InquiryConfig()
        assert cfg.max_loops == 3
        assert cfg.max_sources_per_query == 3
        assert cfg.parallel_queries is True
        assert "web" in cfg.source_profiles
        assert "code" in cfg.source_profiles
        assert "deep" in cfg.source_profiles

    def test_custom_config(self) -> None:
        cfg = InquiryConfig(max_loops=5, max_sources_per_query=2)
        assert cfg.max_loops == 5
        assert cfg.max_sources_per_query == 2

    def test_validation_bounds(self) -> None:
        with pytest.raises(ValueError):
            InquiryConfig(max_loops=0)
        with pytest.raises(ValueError):
            InquiryConfig(max_loops=11)


# ---------------------------------------------------------------------------
# Mock source for testing router
# ---------------------------------------------------------------------------


class MockSource:
    """Minimal InformationSource implementation for testing."""

    def __init__(self, name: str, source_type: str, score: float) -> None:
        self._name = name
        self._source_type = source_type
        self._score = score

    @property
    def name(self) -> str:
        return self._name

    @property
    def source_type(self) -> str:
        return self._source_type

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        return [
            SourceResult(
                content=f"Mock result from {self._name} for: {query}",
                source_ref=self._name,
                source_name=self._name,
            )
        ]

    def relevance_score(self, query: str) -> float:
        return self._score


class TestProtocolCompliance:
    def test_mock_source_satisfies_protocol(self) -> None:
        src = MockSource("test", "web", 0.5)
        assert isinstance(src, InformationSource)

    def test_protocol_properties(self) -> None:
        src = MockSource("my_source", "filesystem", 0.8)
        assert src.name == "my_source"
        assert src.source_type == "filesystem"
        assert src.relevance_score("anything") == 0.8


# ---------------------------------------------------------------------------
# Source scoring tests
# ---------------------------------------------------------------------------


class TestSourceScoring:
    def test_web_source_scoring(self) -> None:
        from soothe.inquiry.sources.web import WebSource

        src = WebSource()
        assert src.relevance_score("latest news about AI") > 0.3
        assert src.relevance_score("src/main.py line 42") < 0.4

    def test_academic_source_scoring(self) -> None:
        from soothe.inquiry.sources.academic import AcademicSource

        src = AcademicSource()
        assert src.relevance_score("research papers on transformer architecture") > 0.3
        assert src.relevance_score("delete all files") < 0.15

    def test_filesystem_source_scoring(self) -> None:
        from soothe.inquiry.sources.filesystem import FilesystemSource

        src = FilesystemSource()
        assert src.relevance_score("authentication module in the codebase") > 0.3
        assert src.relevance_score("src/auth/module.py") > 0.5
        assert src.relevance_score("latest news") < 0.3

    def test_cli_source_scoring(self) -> None:
        from soothe.inquiry.sources.cli import CLISource

        src = CLISource()
        assert src.relevance_score("$ git log") > 0.5
        assert src.relevance_score("git history of this repo") > 0.1
        assert src.relevance_score("what is machine learning") < 0.1

    def test_browser_source_scoring(self) -> None:
        from soothe.inquiry.sources.browser import BrowserSource

        src = BrowserSource()
        assert src.relevance_score("https://example.com/dashboard") > 0.7
        assert src.relevance_score("simple factual question") < 0.2

    def test_document_source_scoring(self) -> None:
        from soothe.inquiry.sources.document import DocumentSource

        src = DocumentSource()
        assert src.relevance_score("what does the spec.pdf say about auth") > 0.5
        assert src.relevance_score("simple web query") < 0.15


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------


class TestSourceRouter:
    def test_selects_highest_scoring(self) -> None:
        from soothe.inquiry.router import SourceRouter

        sources = [
            MockSource("low", "web", 0.2),
            MockSource("high", "web", 0.9),
            MockSource("mid", "web", 0.5),
        ]
        router = SourceRouter(sources)
        selected = router.select("test query")
        assert selected[0].name == "high"

    def test_respects_max_sources(self) -> None:
        from soothe.inquiry.router import SourceRouter

        sources = [
            MockSource("a", "web", 0.9),
            MockSource("b", "academic", 0.8),
            MockSource("c", "filesystem", 0.7),
            MockSource("d", "cli", 0.6),
        ]
        config = InquiryConfig(max_sources_per_query=2)
        router = SourceRouter(sources, config)
        selected = router.select("test query")
        assert len(selected) == 2

    def test_domain_filtering(self) -> None:
        from soothe.inquiry.router import SourceRouter

        sources = [
            MockSource("web1", "web", 0.9),
            MockSource("fs1", "filesystem", 0.9),
            MockSource("cli1", "cli", 0.9),
        ]
        config = InquiryConfig()
        router = SourceRouter(sources, config)
        selected = router.select("test query", domain="code")
        source_types = {s.source_type for s in selected}
        assert "web" not in source_types

    def test_fallback_when_no_relevant(self) -> None:
        from soothe.inquiry.router import SourceRouter

        sources = [MockSource("only", "web", 0.05)]
        router = SourceRouter(sources)
        selected = router.select("irrelevant query")
        assert len(selected) >= 1

    def test_auto_domain_uses_all(self) -> None:
        from soothe.inquiry.router import SourceRouter

        sources = [
            MockSource("web1", "web", 0.8),
            MockSource("fs1", "filesystem", 0.7),
        ]
        router = SourceRouter(sources)
        selected = router.select("test query", domain="auto")
        assert len(selected) == 2

    def test_available_source_types(self) -> None:
        from soothe.inquiry.router import SourceRouter

        sources = [
            MockSource("a", "web", 0.5),
            MockSource("b", "filesystem", 0.5),
            MockSource("c", "web", 0.5),
        ]
        router = SourceRouter(sources)
        types = router.available_source_types()
        assert types == ["web", "filesystem"]


# ---------------------------------------------------------------------------
# CLI source command translation tests
# ---------------------------------------------------------------------------


class TestCLISourceCommandTranslation:
    def test_direct_command(self) -> None:
        from soothe.inquiry.sources.cli import CLISource

        assert CLISource._query_to_command("$ ls -la") == "ls -la"

    def test_git_log_mapping(self) -> None:
        from soothe.inquiry.sources.cli import CLISource

        cmd = CLISource._query_to_command("show me the git log")
        assert "git log" in cmd

    def test_unknown_returns_empty(self) -> None:
        from soothe.inquiry.sources.cli import CLISource

        cmd = CLISource._query_to_command("what is the meaning of life")
        assert cmd == ""


# ---------------------------------------------------------------------------
# Filesystem source helpers
# ---------------------------------------------------------------------------


class TestFilesystemSourceHelpers:
    def test_looks_like_path(self) -> None:
        from soothe.inquiry.sources.filesystem import FilesystemSource

        assert FilesystemSource._looks_like_path("src/auth/module.py")
        assert FilesystemSource._looks_like_path("./config.yml")
        assert not FilesystemSource._looks_like_path("latest news")
        assert not FilesystemSource._looks_like_path("https://example.com")

    def test_query_to_pattern(self) -> None:
        from soothe.inquiry.sources.filesystem import FilesystemSource

        pattern = FilesystemSource._query_to_pattern("authentication module handler")
        assert "authentication" in pattern


# ---------------------------------------------------------------------------
# Document source helpers
# ---------------------------------------------------------------------------


class TestDocumentSourceHelpers:
    def test_split_path_question(self) -> None:
        from soothe.inquiry.sources.document import DocumentSource

        path, q = DocumentSource._split_path_question("spec.pdf: what is the API?")
        assert path == "spec.pdf"
        assert "API" in q

    def test_split_no_path(self) -> None:
        from soothe.inquiry.sources.document import DocumentSource

        path, q = DocumentSource._split_path_question("what is machine learning")
        assert path == ""


# ---------------------------------------------------------------------------
# Research subagent integration (no LLM call -- just structure check)
# ---------------------------------------------------------------------------


class TestResearchSubagentRefactor:
    def test_description_updated(self) -> None:
        from soothe.subagents.research import RESEARCH_DESCRIPTION

        assert "multi-source" in RESEARCH_DESCRIPTION.lower()

    def test_build_inquiry_sources(self) -> None:
        from soothe.subagents.research import _build_inquiry_sources

        sources = _build_inquiry_sources()
        assert len(sources) == 2
        types = {s.source_type for s in sources}
        assert "web" in types
        assert "academic" in types


# ---------------------------------------------------------------------------
# Inquiry tool structure tests
# ---------------------------------------------------------------------------


class TestInquiryTool:
    def test_tool_metadata(self) -> None:
        from soothe.tools.inquiry import InquiryTool

        tool = InquiryTool()
        assert tool.name == "inquiry"
        assert "domain" in tool.description.lower()
        assert "deep" in tool.description.lower()

    def test_build_sources_web(self) -> None:
        from soothe.tools.inquiry import InquiryTool

        tool = InquiryTool()
        sources = tool._build_sources("web")
        types = {s.source_type for s in sources}
        assert "web" in types
        assert "academic" in types
        assert "filesystem" not in types

    def test_build_sources_code(self) -> None:
        from soothe.tools.inquiry import InquiryTool

        tool = InquiryTool()
        sources = tool._build_sources("code")
        types = {s.source_type for s in sources}
        assert "filesystem" in types
        assert "cli" in types
        assert "web" not in types

    def test_build_sources_deep(self) -> None:
        from soothe.tools.inquiry import InquiryTool

        tool = InquiryTool()
        sources = tool._build_sources("deep")
        types = {s.source_type for s in sources}
        assert len(types) >= 4

    def test_build_sources_auto(self) -> None:
        from soothe.tools.inquiry import InquiryTool

        tool = InquiryTool()
        sources = tool._build_sources("auto")
        assert len(sources) >= 3


# ---------------------------------------------------------------------------
# Prompt integration
# ---------------------------------------------------------------------------


class TestPromptIntegration:
    def test_tool_orchestration_guide_mentions_inquiry(self) -> None:
        from soothe.config.prompts import _TOOL_ORCHESTRATION_GUIDE

        assert "inquiry" in _TOOL_ORCHESTRATION_GUIDE.lower()
        assert "domain" in _TOOL_ORCHESTRATION_GUIDE.lower()
