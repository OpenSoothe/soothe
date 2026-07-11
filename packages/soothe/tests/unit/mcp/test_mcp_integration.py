"""Unit tests for MCP progressive loading integration."""

from unittest.mock import MagicMock

import pytest

from soothe.mcp.name_utils import parse_mcp_tool_name
from soothe.middleware.mcp_activation import MCPActivationMiddleware


class TestMCPNameParsing:
    """Tests for MCP tool name parsing."""

    def test_parse_mcp_tool_name(self) -> None:
        parsed = parse_mcp_tool_name("mcp__github__create_issue")
        assert parsed == ("github", "create_issue")

    def test_parse_non_mcp_returns_none(self) -> None:
        assert parse_mcp_tool_name("read_file") is None


class TestMCPActivationMiddleware:
    """Smoke tests for MCPActivationMiddleware."""

    def test_init(self) -> None:
        registry = MagicMock()
        registry.always_loaded_tools.return_value = []
        registry.deferred_tools.return_value = []
        mw = MCPActivationMiddleware(mcp_registry=registry)
        assert mw._registry is registry

    @pytest.mark.asyncio
    async def test_abefore_agent_skips_existing(self) -> None:
        registry = MagicMock()
        registry.always_loaded_tools.return_value = []
        mw = MCPActivationMiddleware(mcp_registry=registry)
        existing = {
            "mcp_activation": {"sent": set(), "promoted": set()},
            "disabled_mcp_servers": set(),
            "cached_mcp_resources": {},
        }
        updates = await mw.abefore_agent(existing, MagicMock())
        assert updates is None

    @pytest.mark.asyncio
    async def test_awrap_tool_call_non_mcp_passes_through(self) -> None:
        registry = MagicMock()
        registry.always_loaded_tools.return_value = []
        registry.deferred_tools.return_value = []
        mw = MCPActivationMiddleware(mcp_registry=registry)

        request = MagicMock()
        request.tool_call = {"name": "read_file", "args": {"path": "/tmp"}}
        request.state = {"mcp_activation": {"sent": set(), "promoted": set()}}

        async def async_handler(req):
            return "result"

        result = await mw.awrap_tool_call(request, async_handler)
        assert result == "result"
