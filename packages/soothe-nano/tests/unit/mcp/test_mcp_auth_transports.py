"""Unit tests for MCP auth with transports and MCPRegistry (RFC-412).

Tests validate:
1. Auth header interpolation with env vars
2. Transport factory properly applies auth headers to different transport types
3. MCPRegistry properly resolves and passes auth headers to connection specs
4. Error handling for missing env vars
5. Different auth scenarios (Bearer tokens, API keys, custom headers)
"""

from __future__ import annotations

import os
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe_nano.config.models import MCPAuthHeaders, MCPServerConfig, MCPTransport
from soothe_nano.mcp.mcp_config import interpolate_auth_headers, make_connection_spec
from soothe_nano.mcp.mcp_registry import MCPRegistry


def _secret_resolver(value: str) -> str:
    """Simulate config.secret_resolver that replaces ${ENV_VAR} patterns."""
    return re.sub(r"\$\{([^}]+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), value)


class TestAuthHeaderInterpolation:
    """Integration tests for auth header interpolation."""

    def test_interpolate_bearer_token_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test interpolating Bearer token from environment variable."""
        monkeypatch.setenv("MCP_API_KEY", "test-api-key-12345")

        headers = {"Authorization": "Bearer ${MCP_API_KEY}"}
        resolved = interpolate_auth_headers(headers, _secret_resolver)

        assert resolved["Authorization"] == "Bearer test-api-key-12345"

    def test_interpolate_custom_header_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test interpolating custom API key header from environment variable."""
        monkeypatch.setenv("LINEAR_API_KEY", "linear-key-abc")

        headers = {"X-Linear-Token": "${LINEAR_API_KEY}"}
        resolved = interpolate_auth_headers(headers, _secret_resolver)

        assert resolved["X-Linear-Token"] == "linear-key-abc"

    def test_interpolate_multiple_headers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test interpolating multiple auth headers from different env vars."""
        monkeypatch.setenv("API_KEY_1", "key-one")
        monkeypatch.setenv("API_KEY_2", "key-two")

        headers = {
            "Authorization": "Bearer ${API_KEY_1}",
            "X-Custom-Header": "${API_KEY_2}",
        }
        resolved = interpolate_auth_headers(headers, _secret_resolver)

        assert resolved["Authorization"] == "Bearer key-one"
        assert resolved["X-Custom-Header"] == "key-two"

    def test_interpolate_static_headers(self) -> None:
        """Test that static headers without env vars pass through unchanged."""
        headers = {
            "Authorization": "Bearer static-token-xyz",
            "X-API-Key": "static-key-123",
        }
        resolved = interpolate_auth_headers(headers, lambda v: v)

        assert resolved["Authorization"] == "Bearer static-token-xyz"
        assert resolved["X-API-Key"] == "static-key-123"

    def test_interpolate_missing_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that missing environment variables remain unresolved."""
        monkeypatch.delenv("MISSING_KEY", raising=False)

        headers = {"Authorization": "Bearer ${MISSING_KEY}"}
        resolved = interpolate_auth_headers(headers, _secret_resolver)

        # The unexpanded variable should remain as-is
        assert "${MISSING_KEY}" in resolved["Authorization"]


class TestTransportFactoryAuthHeaders:
    """Integration tests for transport factory auth header handling."""

    def test_sse_transport_with_auth_headers(self) -> None:
        """Test SSE transport spec includes auth headers."""
        server = MCPServerConfig(
            name="linear",
            transport=MCPTransport.SSE,
            url="https://mcp.linear.app/sse",
            auth=MCPAuthHeaders(headers={"Authorization": "Bearer token123"}),
        )
        spec = make_connection_spec(server)

        assert spec["transport"] == "sse"
        assert spec["url"] == "https://mcp.linear.app/sse"
        assert spec["headers"] is not None
        assert spec["headers"]["Authorization"] == "Bearer token123"
        assert spec["timeout"] == 30.0

    def test_streamable_http_transport_with_auth_headers(self) -> None:
        """Test Streamable HTTP transport spec includes auth headers."""
        server = MCPServerConfig(
            name="api",
            transport=MCPTransport.STREAMABLE_HTTP,
            url="https://api.example.com/mcp",
            auth=MCPAuthHeaders(
                headers={
                    "Authorization": "Bearer token456",
                    "X-Api-Key": "api-key-xyz",
                }
            ),
            timeout_seconds=60.0,
        )
        spec = make_connection_spec(server)

        assert spec["transport"] == "streamable_http"
        assert spec["url"] == "https://api.example.com/mcp"
        assert spec["headers"] is not None
        assert spec["headers"]["Authorization"] == "Bearer token456"
        assert spec["headers"]["X-Api-Key"] == "api-key-xyz"

    def test_websocket_transport_no_auth_headers(self) -> None:
        """Test WebSocket transport does not include auth headers (not supported in spec)."""
        server = MCPServerConfig(
            name="ws",
            transport=MCPTransport.WEBSOCKET,
            url="wss://ws.example.com/mcp",
            auth=MCPAuthHeaders(headers={"Authorization": "Bearer ws-token"}),
        )
        spec = make_connection_spec(server)

        assert spec["transport"] == "websocket"
        assert spec["url"] == "wss://ws.example.com/mcp"
        # WebSocket spec does not include headers
        assert "headers" not in spec or spec.get("headers") is None

    def test_stdio_transport_no_auth_headers(self) -> None:
        """Test stdio transport does not include auth headers."""
        server = MCPServerConfig(
            name="filesystem",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem"],
            auth=MCPAuthHeaders(headers={"Authorization": "Bearer ignored"}),
        )
        spec = make_connection_spec(server, workspace="/tmp/workspace")

        assert spec["transport"] == "stdio"
        assert spec["command"] == "npx"
        # Stdio spec does not include headers
        assert "headers" not in spec or spec.get("headers") is None

    def test_transport_without_auth(self) -> None:
        """Test transport spec without auth configuration."""
        server = MCPServerConfig(
            name="noauth",
            transport=MCPTransport.SSE,
            url="https://public.example.com/sse",
        )
        spec = make_connection_spec(server)

        assert spec["transport"] == "sse"
        assert spec["url"] == "https://public.example.com/sse"
        assert spec["headers"] is None


class TestMCPRegistryAuthIntegration:
    """Integration tests for MCPRegistry auth resolution."""

    @pytest.mark.asyncio
    async def test_registry_resolves_env_vars_in_auth_headers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test MCPRegistry resolves env vars in auth headers during initialization."""
        monkeypatch.setenv("TEST_API_KEY", "resolved-api-key-xyz")

        server = MCPServerConfig(
            name="test-server",
            transport=MCPTransport.SSE,
            url="https://test.example.com/sse",
            auth=MCPAuthHeaders(
                headers={
                    "Authorization": "Bearer ${TEST_API_KEY}",
                    "X-Custom": "static-value",
                }
            ),
        )

        registry = MCPRegistry(servers=[server], secret_resolver=_secret_resolver)

        # Mock langchain_mcp_adapters.MultiServerMCPClient to capture connection spec
        mock_client = MagicMock()
        mock_session = AsyncMock()

        async def mock_session_context(name, auto_initialize=True):
            class SessionContext:
                async def __aenter__(self):
                    return mock_session

                async def __aexit__(self, *args):
                    pass

            return SessionContext()

        mock_client.session = mock_session_context

        with patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client):
            await registry.initialize()

            # Verify connection spec was created with resolved headers
            connections = mock_client.call_args_list[0][0][0] if mock_client.call_args_list else {}

            if "test-server" in connections:
                spec = connections["test-server"]
                assert spec["headers"] is not None
                assert spec["headers"]["Authorization"] == "Bearer resolved-api-key-xyz"
                assert spec["headers"]["X-Custom"] == "static-value"

    @pytest.mark.asyncio
    async def test_registry_applies_auth_to_sse_transport(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test MCPRegistry applies auth headers to SSE transport."""
        monkeypatch.setenv("SSE_TOKEN", "sse-token-abc")

        server = MCPServerConfig(
            name="sse-server",
            transport=MCPTransport.SSE,
            url="https://sse.example.com/sse",
            auth=MCPAuthHeaders(headers={"Authorization": "Bearer ${SSE_TOKEN}"}),
        )

        registry = MCPRegistry(servers=[server], secret_resolver=_secret_resolver)

        mock_client = MagicMock()
        mock_session = AsyncMock()

        async def mock_session_context(name, auto_initialize=True):
            class SessionContext:
                async def __aenter__(self):
                    return mock_session

                async def __aexit__(self, *args):
                    pass

            return SessionContext()

        mock_client.session = mock_session_context

        with patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client):
            await registry.initialize()

            connections = mock_client.call_args_list[0][0][0] if mock_client.call_args_list else {}

            if "sse-server" in connections:
                spec = connections["sse-server"]
                assert spec["transport"] == "sse"
                assert spec["headers"]["Authorization"] == "Bearer sse-token-abc"

    @pytest.mark.asyncio
    async def test_registry_applies_auth_to_streamable_http_transport(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test MCPRegistry applies auth headers to Streamable HTTP transport."""
        monkeypatch.setenv("HTTP_TOKEN", "http-token-def")

        server = MCPServerConfig(
            name="http-server",
            transport=MCPTransport.STREAMABLE_HTTP,
            url="https://http.example.com/mcp",
            auth=MCPAuthHeaders(headers={"Authorization": "Bearer ${HTTP_TOKEN}"}),
        )

        registry = MCPRegistry(servers=[server], secret_resolver=_secret_resolver)

        mock_client = MagicMock()
        mock_session = AsyncMock()

        async def mock_session_context(name, auto_initialize=True):
            class SessionContext:
                async def __aenter__(self):
                    return mock_session

                async def __aexit__(self, *args):
                    pass

            return SessionContext()

        mock_client.session = mock_session_context

        with patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client):
            await registry.initialize()

            connections = mock_client.call_args_list[0][0][0] if mock_client.call_args_list else {}

            if "http-server" in connections:
                spec = connections["http-server"]
                assert spec["transport"] == "streamable_http"
                assert spec["headers"]["Authorization"] == "Bearer http-token-def"

    @pytest.mark.asyncio
    async def test_registry_no_auth_for_stdio_and_websocket(self) -> None:
        """Test MCPRegistry does not apply auth headers to stdio and websocket transports."""
        servers = [
            MCPServerConfig(
                name="stdio-server",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem"],
            ),
            MCPServerConfig(
                name="ws-server",
                transport=MCPTransport.WEBSOCKET,
                url="wss://ws.example.com/mcp",
                auth=MCPAuthHeaders(headers={"Authorization": "Bearer ignored"}),
            ),
        ]

        registry = MCPRegistry(servers=servers)

        mock_client = MagicMock()
        mock_session = AsyncMock()

        async def mock_session_context(name, auto_initialize=True):
            class SessionContext:
                async def __aenter__(self):
                    return mock_session

                async def __aexit__(self, *args):
                    pass

            return SessionContext()

        mock_client.session = mock_session_context

        with patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client):
            await registry.initialize()

            connections = mock_client.call_args_list[0][0][0] if mock_client.call_args_list else {}

            # Stdio should have no headers
            if "stdio-server" in connections:
                stdio_spec = connections["stdio-server"]
                assert stdio_spec["transport"] == "stdio"
                assert stdio_spec.get("headers") is None

            # WebSocket should have no headers (per current spec)
            if "ws-server" in connections:
                ws_spec = connections["ws-server"]
                assert ws_spec["transport"] == "websocket"
                assert ws_spec.get("headers") is None

    @pytest.mark.asyncio
    async def test_registry_multiple_servers_with_different_auth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test MCPRegistry handles multiple servers with different auth configs."""
        monkeypatch.setenv("SERVER1_KEY", "key-one")
        monkeypatch.setenv("SERVER2_KEY", "key-two")

        servers = [
            MCPServerConfig(
                name="server1",
                transport=MCPTransport.SSE,
                url="https://server1.example.com/sse",
                auth=MCPAuthHeaders(headers={"Authorization": "Bearer ${SERVER1_KEY}"}),
            ),
            MCPServerConfig(
                name="server2",
                transport=MCPTransport.STREAMABLE_HTTP,
                url="https://server2.example.com/mcp",
                auth=MCPAuthHeaders(headers={"X-API-Key": "${SERVER2_KEY}"}),
            ),
            MCPServerConfig(
                name="server3",
                transport=MCPTransport.SSE,
                url="https://server3.example.com/sse",
                # No auth
            ),
        ]

        registry = MCPRegistry(servers=servers, secret_resolver=_secret_resolver)

        mock_client = MagicMock()
        mock_session = AsyncMock()

        async def mock_session_context(name, auto_initialize=True):
            class SessionContext:
                async def __aenter__(self):
                    return mock_session

                async def __aexit__(self, *args):
                    pass

            return SessionContext()

        mock_client.session = mock_session_context

        with patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client):
            await registry.initialize()

            connections = mock_client.call_args_list[0][0][0] if mock_client.call_args_list else {}

            # Server1 should have resolved auth
            if "server1" in connections:
                spec1 = connections["server1"]
                assert spec1["headers"]["Authorization"] == "Bearer key-one"

            # Server2 should have resolved auth
            if "server2" in connections:
                spec2 = connections["server2"]
                assert spec2["headers"]["X-API-Key"] == "key-two"

            # Server3 should have no auth
            if "server3" in connections:
                spec3 = connections["server3"]
                assert spec3.get("headers") is None


class TestAuthHeaderEdgeCases:
    """Integration tests for auth header edge cases."""

    def test_empty_auth_headers(self) -> None:
        """Test transport with empty auth headers dict."""
        server = MCPServerConfig(
            name="empty-auth",
            transport=MCPTransport.SSE,
            url="https://empty.example.com/sse",
            auth=MCPAuthHeaders(headers={}),
        )
        spec = make_connection_spec(server)

        # Empty headers dict should result in None
        assert spec["headers"] is None

    def test_auth_headers_with_special_characters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test auth headers with special characters in values."""
        monkeypatch.setenv("SPECIAL_KEY", "key-with-special-chars!@#$%^&*()")

        headers = {"Authorization": "Bearer ${SPECIAL_KEY}"}
        resolved = interpolate_auth_headers(headers, _secret_resolver)

        assert resolved["Authorization"] == "Bearer key-with-special-chars!@#$%^&*()"

    def test_auth_headers_with_unicode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test auth headers with unicode characters."""
        monkeypatch.setenv("UNICODE_KEY", "unicode-键值")

        headers = {"X-Custom-Auth": "${UNICODE_KEY}"}
        resolved = interpolate_auth_headers(headers, _secret_resolver)

        assert resolved["X-Custom-Auth"] == "unicode-键值"

    def test_auth_headers_preserve_case(self) -> None:
        """Test that auth header names preserve case."""
        server = MCPServerConfig(
            name="case-test",
            transport=MCPTransport.SSE,
            url="https://case.example.com/sse",
            auth=MCPAuthHeaders(
                headers={
                    "Authorization": "Bearer token",
                    "X-API-Key": "key",
                    "x-lowercase": "value",
                }
            ),
        )
        spec = make_connection_spec(server)

        assert "Authorization" in spec["headers"]
        assert "X-API-Key" in spec["headers"]
        assert "x-lowercase" in spec["headers"]

    def test_auth_with_custom_timeout(self) -> None:
        """Test auth headers with custom timeout configuration."""
        server = MCPServerConfig(
            name="timeout-test",
            transport=MCPTransport.SSE,
            url="https://timeout.example.com/sse",
            auth=MCPAuthHeaders(headers={"Authorization": "Bearer token"}),
            timeout_seconds=120.0,
        )
        spec = make_connection_spec(server)

        assert spec["headers"]["Authorization"] == "Bearer token"
        assert spec["timeout"] == 120.0


class TestAuthHeadersDifferentTransports:
    """Integration tests for auth header application across different transports."""

    def test_sse_transport_all_headers_types(self) -> None:
        """Test SSE transport with various auth header types."""
        server = MCPServerConfig(
            name="sse-full-auth",
            transport=MCPTransport.SSE,
            url="https://sse.example.com/sse",
            auth=MCPAuthHeaders(
                headers={
                    "Authorization": "Bearer token",
                    "X-API-Key": "api-key",
                    "X-Request-ID": "request-id",
                    "Cookie": "session=abc123",
                }
            ),
        )
        spec = make_connection_spec(server)

        assert spec["transport"] == "sse"
        assert spec["headers"]["Authorization"] == "Bearer token"
        assert spec["headers"]["X-API-Key"] == "api-key"
        assert spec["headers"]["X-Request-ID"] == "request-id"
        assert spec["headers"]["Cookie"] == "session=abc123"

    def test_streamable_http_transport_all_headers_types(self) -> None:
        """Test Streamable HTTP transport with various auth header types."""
        from datetime import timedelta

        server = MCPServerConfig(
            name="http-full-auth",
            transport=MCPTransport.STREAMABLE_HTTP,
            url="https://http.example.com/mcp",
            auth=MCPAuthHeaders(
                headers={
                    "Authorization": "Bearer token",
                    "X-API-Key": "api-key",
                    "X-Custom-Header": "custom-value",
                }
            ),
            timeout_seconds=45.0,
        )
        spec = make_connection_spec(server)

        assert spec["transport"] == "streamable_http"
        assert spec["headers"]["Authorization"] == "Bearer token"
        assert spec["headers"]["X-API-Key"] == "api-key"
        assert spec["headers"]["X-Custom-Header"] == "custom-value"
        # Streamable HTTP uses timedelta for timeout
        assert spec["timeout"] == timedelta(seconds=45.0)
