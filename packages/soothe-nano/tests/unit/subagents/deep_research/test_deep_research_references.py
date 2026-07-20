"""Tests for Deep Research reference collection and formatting."""

from __future__ import annotations

from soothe_nano.subagents.deep_research.protocol import ResearchReference, SourceResult
from soothe_nano.subagents.deep_research.references import (
    format_references_section,
    merge_references,
    reference_from_source_result,
)


class TestReferenceFromSource:
    def test_url_from_metadata(self) -> None:
        result = SourceResult(
            content="snippet",
            source_ref="https://example.com/doc",
            source_name="web_search",
            metadata={"url": "https://example.com/doc", "title": "Example Doc"},
        )
        ref = reference_from_source_result(result, query="test query")
        assert ref.url == "https://example.com/doc"
        assert ref.title == "Example Doc"
        assert ref.query == "test query"


class TestMergeReferences:
    def test_dedupe_by_url(self) -> None:
        refs = [
            ResearchReference(
                url="https://a.com/x",
                title="A",
                source_name="web",
                source_ref="a",
            ),
            ResearchReference(
                url="https://a.com/x/",
                title="A duplicate",
                source_name="web",
                source_ref="a2",
            ),
        ]
        merged = merge_references(refs)
        assert len(merged) == 1


class TestFormatReferences:
    def test_markdown_section(self) -> None:
        refs = [
            ResearchReference(
                url="https://example.com",
                title="Example",
                source_name="web_search",
                source_ref="example.com",
            ),
        ]
        text = format_references_section(refs, accessed_date="2026-05-25")
        assert "## References" in text
        assert "[Example](https://example.com)" in text
        assert "accessed 2026-05-25" in text

    def test_empty_returns_blank(self) -> None:
        assert format_references_section([]) == ""
