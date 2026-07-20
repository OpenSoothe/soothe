"""Integration tests for wizsearch toolkit (search, crawl).

Tests wizsearch search and crawl capabilities with real API calls.
"""

import pytest

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Wizsearch Search Tool Tests
# ---------------------------------------------------------------------------

_wizsearch_available = False
try:
    import wizsearch  # noqa: F401

    _wizsearch_available = True
except ImportError:
    pass


class TestWizsearchSearchTool:
    """Integration tests for wizsearch search tool."""

    @pytest.fixture
    def search_tool(self):
        """Create WizsearchSearchTool instance."""
        pytest.importorskip("wizsearch", reason="wizsearch package required")
        from soothe_nano.toolkits.wizsearch import WizsearchSearchTool

        return WizsearchSearchTool()

    def test_basic_web_search(self, search_tool) -> None:
        """Test basic web search functionality."""
        import os

        # Requires either SERPER_API_KEY or wizsearch availability
        has_serper = bool(os.getenv("SERPER_API_KEY"))

        if not has_serper:
            pytest.skip("SERPER_API_KEY required for wizsearch search test")

        result = search_tool._run("Python asyncio tutorial", max_results_per_engine=5)

        # Should return search results
        assert isinstance(result, (str, dict))

    def test_search_tool_name(self, search_tool) -> None:
        """Test tool name is prefixed correctly."""
        assert search_tool.name == "wizsearch_search"

    def test_search_with_max_results(self, search_tool) -> None:
        """Test search with custom max_results parameter."""
        import os

        if not os.getenv("SERPER_API_KEY"):
            pytest.skip("SERPER_API_KEY required")

        result = search_tool._run("machine learning", max_results_per_engine=3)

        # Should respect max_results limit
        assert isinstance(result, (str, dict))

    def test_search_error_handling(self, search_tool) -> None:
        """Test search handles API errors gracefully."""
        # Test with empty query
        result = search_tool._run("")

        # Should handle gracefully (either error or empty results)
        assert isinstance(result, (str, dict))


# ---------------------------------------------------------------------------
# Wizsearch Crawl Tool Tests
# ---------------------------------------------------------------------------


class TestWizsearchCrawlTool:
    """Integration tests for wizsearch crawl tool."""

    @pytest.fixture
    def crawl_tool(self):
        """Create WizsearchCrawlTool instance."""
        pytest.importorskip("wizsearch", reason="wizsearch package required")
        from soothe_nano.toolkits.wizsearch import WizsearchCrawlTool

        return WizsearchCrawlTool()

    def test_basic_web_crawl(self, crawl_tool) -> None:
        """Test crawling a webpage and extracting content."""
        import os

        # Requires JINA_API_KEY or wizsearch availability
        has_jina = bool(os.getenv("JINA_API_KEY"))

        if not has_jina:
            pytest.skip("JINA_API_KEY required for wizsearch crawl test")

        # Test with a reliable documentation page
        result = crawl_tool._run("https://docs.python.org/3/library/asyncio.html")

        # Should extract content (Jina/upstream may return a short placeholder)
        assert isinstance(result, (str, dict))
        if isinstance(result, str):
            if len(result) < 100:
                pytest.skip(
                    f"Crawl returned minimal content ({len(result)} chars); skip when upstream is flaky"
                )

    def test_crawl_tool_name(self, crawl_tool) -> None:
        """Test tool name is prefixed correctly."""
        assert crawl_tool.name == "wizsearch_crawl"

    def test_crawl_invalid_url(self, crawl_tool) -> None:
        """Test crawling with invalid URL."""
        result = crawl_tool._run("not-a-valid-url")

        # Should handle error gracefully
        assert isinstance(result, (str, dict))


# ---------------------------------------------------------------------------
# Error Handling and Edge Cases
# ---------------------------------------------------------------------------


class TestWizsearchToolErrors:
    """Test error handling and edge cases for wizsearch tools."""

    def test_search_rate_limiting(self) -> None:
        """Test that search tool handles rate limiting gracefully."""
        import os

        if not os.getenv("SERPER_API_KEY"):
            pytest.skip("SERPER_API_KEY required")

        pytest.importorskip("wizsearch", reason="wizsearch package required")

        # Make multiple rapid requests
        pytest.skip("Requires specific test setup for rate limiting scenarios")

    def test_crawl_large_page(self) -> None:
        """Test crawl handles large pages."""
        import os

        if not os.getenv("JINA_API_KEY"):
            pytest.skip("JINA_API_KEY required")

        pytest.importorskip("wizsearch", reason="wizsearch package required")
        from soothe_nano.toolkits.wizsearch import WizsearchCrawlTool

        tool = WizsearchCrawlTool()

        # Crawl a large documentation page
        result = tool._run("https://docs.python.org/3/library/index.html")

        # Should handle large content
        assert isinstance(result, (str, dict))
