"""Unit tests for MCP config validation (RFC-412)."""

import pytest

from soothe_nano.config import SootheConfig
from soothe_nano.config.models import (
    MCPAuthHeaders,
    MCPServerConfig,
    MCPTransport,
    ProgressiveMCPConfig,
)


class TestMCPServerConfigValidation:
    """Tests for MCPServerConfig model validation."""

    def test_stdio_config_valid(self) -> None:
        """Valid stdio config."""
        cfg = MCPServerConfig(
            name="filesystem", command="npx", args=["-y", "@modelcontextprotocol/server-filesystem"]
        )
        assert cfg.transport == MCPTransport.STDIO
        assert cfg.command == "npx"

    def test_sse_config_valid(self) -> None:
        """Valid SSE config."""
        cfg = MCPServerConfig(
            name="linear",
            transport=MCPTransport.SSE,
            url="https://mcp.linear.app/sse",
            auth=MCPAuthHeaders(headers={"Authorization": "Bearer token"}),
        )
        assert cfg.transport == MCPTransport.SSE
        assert cfg.url is not None

    def test_streamable_http_config_valid(self) -> None:
        """Valid streamable_http config."""
        cfg = MCPServerConfig(
            name="api",
            transport=MCPTransport.STREAMABLE_HTTP,
            url="https://api.example.com/mcp",
        )
        assert cfg.transport == MCPTransport.STREAMABLE_HTTP

    def test_websocket_config_valid(self) -> None:
        """Valid websocket config."""
        cfg = MCPServerConfig(
            name="ws",
            transport=MCPTransport.WEBSOCKET,
            url="wss://ws.example.com/mcp",
        )
        assert cfg.transport == MCPTransport.WEBSOCKET

    def test_stdio_requires_command(self) -> None:
        """Stdio transport requires command."""
        with pytest.raises(ValueError, match="stdio requires 'command'"):
            MCPServerConfig(name="bad", transport=MCPTransport.STDIO)

    def test_stdio_cannot_have_url(self) -> None:
        """Stdio transport cannot have url."""
        with pytest.raises(ValueError, match="stdio cannot have 'url'"):
            MCPServerConfig(name="bad", command="echo", url="https://example.com")

    def test_remote_requires_url(self) -> None:
        """Remote transports require url."""
        with pytest.raises(ValueError, match="sse requires 'url'"):
            MCPServerConfig(name="bad", transport=MCPTransport.SSE)

    def test_remote_cannot_have_command(self) -> None:
        """Remote transports cannot have command."""
        with pytest.raises(ValueError, match="sse cannot have 'command'"):
            MCPServerConfig(
                name="bad", transport=MCPTransport.SSE, url="https://example.com", command="echo"
            )

    def test_default_values(self) -> None:
        """Default values applied correctly."""
        cfg = MCPServerConfig(name="test", command="echo")
        assert cfg.enabled is True
        assert cfg.defer is True  # progressive disclosure by default
        assert cfg.tool_filter is None
        assert cfg.timeout_seconds == 30.0
        assert cfg.request_timeout_seconds == 60.0
        assert cfg.tool_timeout_seconds == 600.0


class TestProgressiveMCPConfig:
    """Tests for ProgressiveMCPConfig."""

    def test_default_values(self) -> None:
        """Default budget values."""
        cfg = ProgressiveMCPConfig()
        assert cfg.budget_pct == 0.01
        assert cfg.max_listing_chars_per_entry == 250
        assert cfg.min_listing_chars_per_entry == 20

    def test_budget_pct_bounds(self) -> None:
        """budget_pct must be between 0 and 1."""
        ProgressiveMCPConfig(budget_pct=0.5)  # valid

        with pytest.raises(ValueError):
            ProgressiveMCPConfig(budget_pct=-0.1)

        with pytest.raises(ValueError):
            ProgressiveMCPConfig(budget_pct=1.1)


class TestSootheConfigMcpValidation:
    """Tests for SootheConfig MCP server unique name validation."""

    def test_unique_names_valid(self) -> None:
        """Unique server names are valid."""
        cfg = SootheConfig(
            mcp_servers=[
                MCPServerConfig(name="github", command="echo"),
                MCPServerConfig(name="linear", command="echo"),
            ]
        )
        assert len(cfg.mcp_servers) == 2

    def test_duplicate_names_invalid(self) -> None:
        """Duplicate server names raise validation error."""
        with pytest.raises(ValueError, match="MCP server names must be unique"):
            SootheConfig(
                mcp_servers=[
                    MCPServerConfig(name="dup", command="a"),
                    MCPServerConfig(name="dup", command="b"),
                ]
            )

    def test_empty_mcp_servers_valid(self) -> None:
        """Empty mcp_servers list is valid."""
        cfg = SootheConfig()
        assert cfg.mcp_servers == []
