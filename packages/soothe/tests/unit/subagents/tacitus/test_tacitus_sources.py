"""Unit tests for Tacitus gather sources."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.subagents.tacitus.protocol import GatherContext
from soothe.subagents.tacitus.sources.academic import AcademicSearchSource
from soothe.subagents.tacitus.sources.url_crawl import UrlCrawlSource


@pytest.fixture
def gather_context() -> GatherContext:
    return GatherContext(topic="test")


class TestAcademicAuthCircuitBreaker:
    """Academic source stops after first DeepXiv auth failure."""

    async def test_skips_follow_up_queries_after_auth_error(self, gather_context: GatherContext):
        source = AcademicSearchSource()
        mock_tool = MagicMock()
        mock_tool.name = "deepxiv_search"
        mock_tool._arun = AsyncMock(
            return_value="Error: Invalid DeepXiv token. Set DEEPXIV_API_KEY",
        )
        source._deepxiv_tool = mock_tool
        source._tools_loaded = True

        first = await source.query("MoE papers", gather_context)
        second = await source.query("Mamba SSM", gather_context)

        assert first == []
        assert second == []
        assert mock_tool._arun.await_count == 1
        assert source._auth_failed is True


class TestAcademicSearchSourcePoliteClient:
    """AcademicSearchSource uses PoliteHTTPClient for rate limiting."""

    async def test_uses_polite_client_when_configured(self, gather_context: GatherContext):
        """AcademicSearchSource wraps DeepXiv calls with polite client when enabled."""
        from soothe.subagents.tacitus.protocol import TacitusConfig

        config = TacitusConfig(enable_polite_concurrency=True)
        source = AcademicSearchSource(config=config)

        # Mock the DeepXiv tool
        mock_tool = MagicMock()
        mock_tool.name = "deepxiv_search"
        mock_tool._arun = AsyncMock(return_value="Found 1 papers:\\n\\n**2409.05591** - Test Paper")
        source._deepxiv_tool = mock_tool
        source._tools_loaded = True

        results = await source.query("quantum computing papers", gather_context)

        # Should have results
        assert len(results) == 1
        assert "quantum" in results[0].metadata.get("query", "").lower()

    async def test_skips_polite_client_when_disabled(self, gather_context: GatherContext):
        """AcademicSearchSource skips polite client when disabled."""
        from soothe.subagents.tacitus.protocol import TacitusConfig

        config = TacitusConfig(enable_polite_concurrency=False)
        source = AcademicSearchSource(config=config)

        # Mock the DeepXiv tool
        mock_tool = MagicMock()
        mock_tool.name = "deepxiv_search"
        mock_tool._arun = AsyncMock(return_value="Found 1 papers:\\n\\n**2409.05591** - Test Paper")
        source._deepxiv_tool = mock_tool
        source._tools_loaded = True

        results = await source.query("neural networks", gather_context)

        # Should have results without polite client
        assert len(results) == 1
        # Polite client should be None when disabled
        assert source._get_polite_client() is None

    async def test_polite_client_respects_deepxiv_rate_limits(self, gather_context: GatherContext):
        """AcademicSearchSource configures polite client with DeepXiv-specific limits."""
        from soothe.subagents.tacitus.protocol import TacitusConfig

        config = TacitusConfig(
            enable_polite_concurrency=True,
            polite_rate_limit_rps=2.0,
            polite_burst_size=5,
            polite_max_concurrent=8,
        )
        source = AcademicSearchSource(config=config)

        polite_client = source._get_polite_client()
        assert polite_client is not None

        # Check that DeepXiv rate limit is configured
        rate_limit = polite_client.rate_limiter.config.get_limit("deepxiv")
        assert rate_limit.rps == 2.0
        assert rate_limit.burst == 5
        assert rate_limit.concurrent == 8

    async def test_polite_client_applies_circuit_breaker_config(
        self, gather_context: GatherContext
    ):
        """AcademicSearchSource configures circuit breaker settings."""
        from soothe.subagents.tacitus.protocol import TacitusConfig

        config = TacitusConfig(
            enable_polite_concurrency=True,
            polite_circuit_breaker_threshold=3,
            polite_circuit_breaker_reset_sec=30.0,
        )
        source = AcademicSearchSource(config=config)

        polite_client = source._get_polite_client()
        assert polite_client is not None

        # Check circuit breaker settings
        assert polite_client.circuit_breaker_threshold == 3
        assert polite_client.circuit_breaker_reset_sec == 30.0

    async def test_polite_client_applies_retry_config(self, gather_context: GatherContext):
        """AcademicSearchSource configures retry settings."""
        from soothe.subagents.tacitus.protocol import TacitusConfig

        config = TacitusConfig(
            enable_polite_concurrency=True,
            polite_retry_max=5,
            polite_retry_base_delay=2.0,
        )
        source = AcademicSearchSource(config=config)

        polite_client = source._get_polite_client()
        assert polite_client is not None

        # Check retry settings
        assert polite_client.max_retries == 5
        assert polite_client.base_delay == 2.0


class TestUrlCrawlSourcePoliteClient:
    """UrlCrawlSource uses PoliteHTTPClient for rate limiting."""

    async def test_uses_polite_client_for_url_crawl(self, gather_context: GatherContext):
        """UrlCrawlSource wraps crawl calls with polite client."""
        source = UrlCrawlSource()

        # Mock the crawl tool
        mock_crawl_tool = MagicMock()
        mock_crawl_tool._arun = AsyncMock(return_value="Extracted content from example.com")
        source._crawl_tool = mock_crawl_tool

        # Mock the polite client to capture calls
        with patch.object(source, "_get_polite_client") as mock_get_client:
            mock_polite_client = MagicMock()
            mock_polite_client.request = AsyncMock(
                return_value="Extracted content from example.com"
            )
            mock_get_client.return_value = mock_polite_client

            results = await source.query("Check https://example.com/page", gather_context)

            # Should use polite client
            assert mock_get_client.called
            assert mock_polite_client.request.called
            assert len(results) == 1
            assert results[0].content == "Extracted content from example.com"

    async def test_polite_client_respects_domain_overrides(self, gather_context: GatherContext):
        """UrlCrawlSource configures polite client with domain overrides."""
        config = {
            "polite": {
                "domain_overrides": {"example.com": {"rps": 0.5, "burst": 2, "concurrent": 3}}
            }
        }
        source = UrlCrawlSource(config=config)

        # Get the polite client
        polite_client = source._get_polite_client()

        # Check that rate limiter config has the override
        rate_limit = polite_client.rate_limiter.config.get_limit("example.com")
        assert rate_limit.rps == 0.5
        assert rate_limit.burst == 2
        assert rate_limit.concurrent == 3

    async def test_polite_client_uses_default_for_unknown_domains(
        self, gather_context: GatherContext
    ):
        """UrlCrawlSource uses default rate limits for unknown domains."""
        source = UrlCrawlSource(config={})

        polite_client = source._get_polite_client()
        rate_limit = polite_client.rate_limiter.config.get_limit("unknown-site.com")

        # Should use default limits
        assert rate_limit.rps > 0
        assert rate_limit.burst >= 1
        assert rate_limit.concurrent >= 1

    async def test_crawl_with_error_returns_empty(self, gather_context: GatherContext):
        """UrlCrawlSource returns empty list on crawl errors."""
        source = UrlCrawlSource()

        # Mock the crawl tool to return error
        mock_crawl_tool = MagicMock()
        mock_crawl_tool._arun = AsyncMock(return_value="Error: Connection failed")
        source._crawl_tool = mock_crawl_tool

        with patch.object(source, "_get_polite_client") as mock_get_client:
            mock_polite_client = MagicMock()
            mock_polite_client.request = AsyncMock(return_value="Error: Connection failed")
            mock_get_client.return_value = mock_polite_client

            results = await source.query("Check https://example.com/page", gather_context)

            # Error responses should not be included
            assert results == []

    async def test_no_urls_in_query_returns_empty(self, gather_context: GatherContext):
        """UrlCrawlSource returns empty when no URLs found in query."""
        source = UrlCrawlSource()

        results = await source.query("Just some text without URLs", gather_context)

        assert results == []

    async def test_multiple_urls_limited_to_two(self, gather_context: GatherContext):
        """UrlCrawlSource limits to 2 URLs per query."""
        source = UrlCrawlSource()

        mock_crawl_tool = MagicMock()
        mock_crawl_tool._arun = AsyncMock(return_value="Content")
        source._crawl_tool = mock_crawl_tool

        call_count = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return f"Content {call_count}"

        with patch.object(source, "_get_polite_client") as mock_get_client:
            mock_polite_client = MagicMock()
            mock_polite_client.request = mock_request
            mock_get_client.return_value = mock_polite_client

            results = await source.query(
                "Check https://a.com/1 and https://b.com/2 and https://c.com/3", gather_context
            )

            # Should only process 2 URLs
            assert len(results) == 2
            assert call_count == 2
