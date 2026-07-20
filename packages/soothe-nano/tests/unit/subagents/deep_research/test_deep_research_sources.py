"""Tests for deep_research web search source."""

from __future__ import annotations

from soothe_nano.subagents.deep_research.sources.web_search import WebSearchSource


def test_web_search_source_name() -> None:
    assert WebSearchSource().name == "web_search"
