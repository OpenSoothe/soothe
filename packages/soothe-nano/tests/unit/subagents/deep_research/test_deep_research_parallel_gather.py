"""Tests for url_crawl toolkit."""

from __future__ import annotations

from soothe_nano.subagents.deep_research.protocol import SourceResult
from soothe_nano.toolkits.url_crawl.crawler import extract_urls, urls_from_search_results


def test_extract_urls_from_text() -> None:
    urls = extract_urls("See https://example.com/a and https://example.org/b")
    assert urls == ["https://example.com/a", "https://example.org/b"]


def test_urls_from_search_results_metadata() -> None:
    results = [
        SourceResult(
            content="snippet",
            source_ref="https://example.com/doc",
            source_name="web_search",
            metadata={"url": "https://example.com/doc", "title": "Doc"},
        )
    ]
    assert urls_from_search_results(results, limit=3) == ["https://example.com/doc"]
