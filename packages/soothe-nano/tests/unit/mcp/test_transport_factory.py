"""Unit tests for MCP transport factory (RFC-412)."""

from datetime import timedelta

from soothe_nano.config.models import MCPAuthHeaders, MCPServerConfig, MCPTransport
from soothe_nano.mcp.mcp_config import make_connection_spec


class TestMakeConnectionSpec:
    """Tests for make_connection_spec."""

    def test_stdio_transport(self) -> None:
        """Stdio transport spec."""
        server = MCPServerConfig(
            name="filesystem",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem"],
            env={"NODE_OPTIONS": "--max-old-space-size=4096"},
        )
        spec = make_connection_spec(server, workspace="/tmp/workspace")

        assert spec["transport"] == "stdio"
        assert spec["command"] == "npx"
        assert spec["args"] == ["-y", "@modelcontextprotocol/server-filesystem"]
        assert spec["env"]["NODE_OPTIONS"] == "--max-old-space-size=4096"
        assert spec["cwd"] == "/tmp/workspace"

    def test_stdio_no_env(self) -> None:
        """Stdio without env dict."""
        server = MCPServerConfig(name="simple", command="python", args=["-m", "mcp_server"])
        spec = make_connection_spec(server)

        assert spec["transport"] == "stdio"
        assert spec["env"] is None  # empty env becomes None

    def test_sse_transport(self) -> None:
        """SSE transport spec."""
        server = MCPServerConfig(
            name="linear",
            transport=MCPTransport.SSE,
            url="https://mcp.linear.app/sse",
            auth=MCPAuthHeaders(headers={"Authorization": "Bearer token123"}),
        )
        spec = make_connection_spec(server)

        assert spec["transport"] == "sse"
        assert spec["url"] == "https://mcp.linear.app/sse"
        assert spec["headers"]["Authorization"] == "Bearer token123"
        assert spec["timeout"] == 30.0  # float for SSE

    def test_streamable_http_transport(self) -> None:
        """Streamable HTTP transport spec (uses timedelta for timeout)."""
        server = MCPServerConfig(
            name="api",
            transport=MCPTransport.STREAMABLE_HTTP,
            url="https://api.example.com/mcp",
            timeout_seconds=60.0,
        )
        spec = make_connection_spec(server)

        assert spec["transport"] == "streamable_http"
        assert spec["url"] == "https://api.example.com/mcp"
        assert spec["timeout"] == timedelta(seconds=60.0)  # timedelta for streamable_http

    def test_websocket_transport(self) -> None:
        """WebSocket transport spec."""
        server = MCPServerConfig(
            name="ws",
            transport=MCPTransport.WEBSOCKET,
            url="wss://ws.example.com/mcp",
        )
        spec = make_connection_spec(server)

        assert spec["transport"] == "websocket"
        assert spec["url"] == "wss://ws.example.com/mcp"

    def test_no_auth_headers(self) -> None:
        """Server without auth config."""
        server = MCPServerConfig(
            name="noauth",
            transport=MCPTransport.SSE,
            url="https://public.example.com/sse",
        )
        spec = make_connection_spec(server)

        assert spec["headers"] is None

    def test_custom_timeout(self) -> None:
        """Custom timeout_seconds."""
        server = MCPServerConfig(
            name="slow",
            transport=MCPTransport.SSE,
            url="https://slow.example.com/sse",
            timeout_seconds=120.0,
        )
        spec = make_connection_spec(server)

        assert spec["timeout"] == 120.0
