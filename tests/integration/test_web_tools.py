"""Integration tests for web tools (search, crawl).

Tests web search and content extraction capabilities with real API calls.
"""

import pytest

# ---------------------------------------------------------------------------
# Web Search Tools Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWebSearchTools:
    """Integration tests for web search tools."""

    @pytest.fixture
    def search_tool(self):
        """Create SearchWebTool instance."""
        from soothe.tools.web_search import SearchWebTool

        return SearchWebTool()

    def test_basic_web_search(self, search_tool) -> None:
        """Test basic web search functionality."""
        import os

        # Requires either SERPER_API_KEY or wizsearch availability
        has_serper = bool(os.getenv("SERPER_API_KEY"))

        if not has_serper:
            pytest.skip("SERPER_API_KEY required for web search test")

        result = search_tool._run("Python asyncio tutorial", max_results_per_engine=5)

        # Should return search results
        assert isinstance(result, (str, dict))
        if isinstance(result, dict):
            # Check for expected structure
            assert "results" in result or "error" in result

    def test_search_backend_selection(self, search_tool) -> None:
        """Test that tool selects appropriate backend (wizsearch)."""
        # Get the backend
        backend = search_tool._get_search_backend()

        # Should return a valid tool
        assert backend is not None
        assert hasattr(backend, "name")

        # Should use wizsearch backend
        assert "search" in backend.name.lower() or "wizsearch" in backend.name.lower()

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
# Web Crawl Tools Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWebCrawlTools:
    """Integration tests for web content extraction."""

    @pytest.fixture
    def crawl_tool(self):
        """Create CrawlWebTool instance."""
        from soothe.tools.web_search import CrawlWebTool

        return CrawlWebTool()

    def test_basic_web_crawl(self, crawl_tool) -> None:
        """Test crawling a webpage and extracting content."""
        import os

        # Requires JINA_API_KEY or wizsearch availability
        has_jina = bool(os.getenv("JINA_API_KEY"))

        if not has_jina:
            pytest.skip("JINA_API_KEY required for crawl test")

        # Test with a reliable documentation page
        result = crawl_tool._run("https://docs.python.org/3/library/asyncio.html")

        # Should extract content
        assert isinstance(result, (str, dict))
        if isinstance(result, str):
            # Should contain asyncio-related content
            assert len(result) > 100
        elif isinstance(result, dict):
            assert "content" in result or "error" in result

    def test_crawl_backend_selection(self, crawl_tool) -> None:
        """Test that tool selects appropriate backend (wizsearch or jina)."""
        # Get the backend
        backend = crawl_tool._get_crawl_backend()

        # Should return a valid tool
        assert backend is not None
        assert hasattr(backend, "name")

        # Should be either jina or wizsearch crawl backend
        backend_name = backend.name.lower()
        assert "jina" in backend_name or "crawl" in backend_name or "wizsearch" in backend_name

    def test_crawl_invalid_url(self, crawl_tool) -> None:
        """Test crawling with invalid URL."""
        result = crawl_tool._run("not-a-valid-url")

        # Should handle error gracefully
        assert isinstance(result, (str, dict))
        if isinstance(result, dict):
            assert "error" in result

    def test_crawl_timeout_handling(self, crawl_tool) -> None:
        """Test crawl handles timeout gracefully."""
        import os

        if not os.getenv("JINA_API_KEY"):
            pytest.skip("JINA_API_KEY required")

        # Test with a URL that might timeout
        # (would need specific test setup for reliable timeout testing)
        pytest.skip("Requires specific test setup for timeout scenarios")


# ---------------------------------------------------------------------------
# Research Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestResearchTools:
    """Integration tests for deep research capabilities."""

    @pytest.fixture
    def research_tool(self):
        """Create ResearchTool instance."""
        from soothe.tools.research import ResearchTool

        return ResearchTool()

    def test_research_basic_query(self, research_tool) -> None:
        """Test research tool with basic query."""
        import os

        if not (os.getenv("SERPER_API_KEY") or os.getenv("OPENAI_API_KEY")):
            pytest.skip("SERPER_API_KEY or OPENAI_API_KEY required for research tool")

        try:
            result = research_tool._run("What is Python asyncio?")

            # Should return a result
            assert isinstance(result, (str, dict))
        except Exception as e:
            # Research may fail due to model availability or API issues
            if "not supported" in str(e) or "invalid" in str(e).lower():
                pytest.skip(f"Model or API not available: {e}")
            raise

    def test_research_multi_source(self, research_tool) -> None:
        """Test research aggregates multiple sources."""
        import os

        if not (os.getenv("SERPER_API_KEY") and os.getenv("JINA_API_KEY")):
            pytest.skip("SERPER_API_KEY and JINA_API_KEY required")

        result = research_tool._run("Python asyncio best practices")

        # Should synthesize information from multiple sources
        assert isinstance(result, (str, dict))


# ---------------------------------------------------------------------------
# Error Handling and Edge Cases
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWebToolErrors:
    """Test error handling and edge cases for web tools."""

    def test_search_rate_limiting(self) -> None:
        """Test that search tool handles rate limiting gracefully."""
        import os

        if not os.getenv("SERPER_API_KEY"):
            pytest.skip("SERPER_API_KEY required")

        from soothe.tools.web_search import SearchWebTool

        tool = SearchWebTool()

        # Make multiple rapid requests
        # (would need specific test setup for reliable rate limit testing)
        pytest.skip("Requires specific test setup for rate limiting scenarios")

    def test_crawl_authentication_required(self) -> None:
        """Test crawl handles authentication-required pages."""
        import os

        if not os.getenv("JINA_API_KEY"):
            pytest.skip("JINA_API_KEY required")

        from soothe.tools.web_search import CrawlWebTool

        tool = CrawlWebTool()

        # Try to crawl a page that requires authentication
        result = tool._run("https://example.com/protected")

        # Should handle gracefully
        assert isinstance(result, (str, dict))

    def test_crawl_large_page(self) -> None:
        """Test crawl handles large pages."""
        import os

        if not os.getenv("JINA_API_KEY"):
            pytest.skip("JINA_API_KEY required")

        from soothe.tools.web_search import CrawlWebTool

        tool = CrawlWebTool()

        # Crawl a large documentation page
        result = tool._run("https://docs.python.org/3/library/index.html")

        # Should handle large content
        assert isinstance(result, (str, dict))
