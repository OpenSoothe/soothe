"""Unit tests for StaticHeadersProvider class (RFC-412)."""

import pytest

from soothe_nano.mcp.mcp_config import StaticHeadersProvider


class TestStaticHeadersProviderInit:
    """Tests for StaticHeadersProvider initialization."""

    def test_init_with_empty_headers(self) -> None:
        """Should initialize with empty headers dict."""
        provider = StaticHeadersProvider({})
        assert provider._headers == {}

    def test_init_with_single_header(self) -> None:
        """Should initialize with single header."""
        provider = StaticHeadersProvider({"Authorization": "Bearer token123"})
        assert provider._headers == {"Authorization": "Bearer token123"}

    def test_init_with_multiple_headers(self) -> None:
        """Should initialize with multiple headers."""
        headers = {
            "Authorization": "Bearer token123",
            "X-API-Key": "api-key-456",
            "X-Custom-Header": "custom-value",
        }
        provider = StaticHeadersProvider(headers)
        assert provider._headers == headers

    def test_init_stores_reference(self) -> None:
        """Should store reference to the original headers dict."""
        original_headers = {"Authorization": "Bearer token"}
        provider = StaticHeadersProvider(original_headers)
        # Provider stores reference (not a copy)
        assert provider._headers is original_headers


class TestStaticHeadersProviderHeaders:
    """Tests for StaticHeadersProvider.headers() method."""

    @pytest.mark.asyncio
    async def test_headers_returns_dict(self) -> None:
        """Should return a dict."""
        provider = StaticHeadersProvider({"Authorization": "Bearer token"})
        result = await provider.headers()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_headers_returns_copy(self) -> None:
        """Should return a copy, not the original dict."""
        provider = StaticHeadersProvider({"Authorization": "Bearer token"})
        result = await provider.headers()
        # Modifying result should not affect internal state
        result["X-New"] = "new-value"
        assert "X-New" not in provider._headers

    @pytest.mark.asyncio
    async def test_headers_returns_empty_dict(self) -> None:
        """Should return empty dict when initialized with empty headers."""
        provider = StaticHeadersProvider({})
        result = await provider.headers()
        assert result == {}

    @pytest.mark.asyncio
    async def test_headers_returns_single_header(self) -> None:
        """Should return single header correctly."""
        provider = StaticHeadersProvider({"Authorization": "Bearer token123"})
        result = await provider.headers()
        assert result == {"Authorization": "Bearer token123"}

    @pytest.mark.asyncio
    async def test_headers_returns_multiple_headers(self) -> None:
        """Should return all headers correctly."""
        headers = {
            "Authorization": "Bearer token123",
            "X-API-Key": "api-key-456",
            "X-Custom-Header": "custom-value",
        }
        provider = StaticHeadersProvider(headers)
        result = await provider.headers()
        assert result == headers

    @pytest.mark.asyncio
    async def test_headers_multiple_calls_return_same_values(self) -> None:
        """Should return same headers across multiple calls."""
        provider = StaticHeadersProvider({"Authorization": "Bearer token"})
        result1 = await provider.headers()
        result2 = await provider.headers()
        assert result1 == result2

    @pytest.mark.asyncio
    async def test_headers_returns_fresh_copy_each_time(self) -> None:
        """Should return a new dict instance each call."""
        provider = StaticHeadersProvider({"Authorization": "Bearer token"})
        result1 = await provider.headers()
        result2 = await provider.headers()
        # Different dict instances
        assert result1 is not result2
        # But same values
        assert result1 == result2


class TestStaticHeadersProviderOn401:
    """Tests for StaticHeadersProvider.on_401() method."""

    @pytest.mark.asyncio
    async def test_on_401_returns_false(self) -> None:
        """Should always return False for static headers."""
        provider = StaticHeadersProvider({"Authorization": "Bearer token"})
        result = await provider.on_401()
        assert result is False

    @pytest.mark.asyncio
    async def test_on_401_returns_false_with_empty_headers(self) -> None:
        """Should return False even with empty headers."""
        provider = StaticHeadersProvider({})
        result = await provider.on_401()
        assert result is False

    @pytest.mark.asyncio
    async def test_on_401_returns_false_multiple_calls(self) -> None:
        """Should consistently return False across multiple calls."""
        provider = StaticHeadersProvider({"Authorization": "Bearer token"})
        result1 = await provider.on_401()
        result2 = await provider.on_401()
        result3 = await provider.on_401()
        assert result1 is False
        assert result2 is False
        assert result3 is False

    @pytest.mark.asyncio
    async def test_on_401_terminal_behavior(self) -> None:
        """Should indicate terminal failure (no retry possible)."""
        provider = StaticHeadersProvider({"Authorization": "Bearer token"})
        result = await provider.on_401()
        # False means "do not retry" - terminal failure
        assert result is False


class TestStaticHeadersProviderIntegration:
    """Integration-style tests for StaticHeadersProvider."""

    @pytest.mark.asyncio
    async def test_full_workflow(self) -> None:
        """Test typical workflow: init, get headers, handle 401."""
        # Initialize
        provider = StaticHeadersProvider(
            {
                "Authorization": "Bearer token123",
                "X-API-Key": "key456",
            }
        )

        # Get headers for request
        headers = await provider.headers()
        assert headers["Authorization"] == "Bearer token123"
        assert headers["X-API-Key"] == "key456"

        # Simulate 401 response
        should_retry = await provider.on_401()
        assert should_retry is False

    @pytest.mark.asyncio
    async def test_headers_returns_copy_not_reference(self) -> None:
        """headers() method should return a copy, not internal reference."""
        provider = StaticHeadersProvider({"Authorization": "Bearer token"})
        headers1 = await provider.headers()
        headers2 = await provider.headers()

        # Different dict instances
        assert headers1 is not headers2
        # But same values
        assert headers1 == headers2

    @pytest.mark.asyncio
    async def test_headers_isolation_between_providers(self) -> None:
        """Each provider instance should have independent headers."""
        provider1 = StaticHeadersProvider({"Authorization": "token1"})
        provider2 = StaticHeadersProvider({"Authorization": "token2"})

        headers1 = await provider1.headers()
        headers2 = await provider2.headers()

        assert headers1["Authorization"] == "token1"
        assert headers2["Authorization"] == "token2"

        # Modifying one should not affect the other
        headers1["X-Custom"] = "custom"
        headers2_again = await provider2.headers()
        assert "X-Custom" not in headers2_again
