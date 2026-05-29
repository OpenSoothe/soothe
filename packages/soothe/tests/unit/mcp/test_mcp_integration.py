"""Unit tests for MCP tool search middleware (RFC-412)."""

from unittest.mock import MagicMock

from soothe.middleware.mcp_tool_search import _MCP_TOOL_PATTERN, MCPToolSearchMiddleware


class TestMCPPattern:
    """Tests for MCP tool name pattern matching."""

    def test_matches_mcp_tool_name(self) -> None:
        assert _MCP_TOOL_PATTERN.match("mcp__github__create_issue")
        assert _MCP_TOOL_PATTERN.match("mcp__server__tool")

    def test_no_match_non_mcp(self) -> None:
        assert _MCP_TOOL_PATTERN.match("read_file") is None
        assert _MCP_TOOL_PATTERN.match("search_web") is None
        assert _MCP_TOOL_PATTERN.match("mcp_tool") is None

    def test_extracts_server_and_tool(self) -> None:
        match = _MCP_TOOL_PATTERN.match("mcp__github__create_issue")
        assert match is not None
        assert match.group(1) == "github"
        assert match.group(2) == "create_issue"


class TestMCPToolSearchMiddleware:
    """Tests for MCPToolSearchMiddleware."""

    def test_init(self) -> None:
        registry = MagicMock()
        mw = MCPToolSearchMiddleware(mcp_registry=registry)
        assert mw._registry is registry

    async def test_abefore_agent_inits_state(self) -> None:
        registry = MagicMock()
        mw = MCPToolSearchMiddleware(mcp_registry=registry)
        updates = await mw.abefore_agent({}, MagicMock())
        assert updates is not None
        assert "sent_mcp_tool_names" in updates
        assert "invoked_mcp_tools" in updates
        assert "disabled_mcp_servers" in updates
        assert "cached_mcp_resources" in updates

    async def test_abefore_agent_skips_existing(self) -> None:
        registry = MagicMock()
        mw = MCPToolSearchMiddleware(mcp_registry=registry)
        existing = {
            "sent_mcp_tool_names": {"mcp__x__y"},
            "invoked_mcp_tools": {},
            "disabled_mcp_servers": set(),
            "cached_mcp_resources": {},
        }
        updates = await mw.abefore_agent(existing, MagicMock())
        assert updates is None

    async def test_awrap_tool_call_non_mcp_passes_through(self) -> None:
        registry = MagicMock()
        mw = MCPToolSearchMiddleware(mcp_registry=registry)

        request = MagicMock()
        request.tool_call = {"name": "read_file", "args": {"path": "/tmp"}}
        request.state = {}

        async def async_handler(req):
            return "result"

        result = await mw.awrap_tool_call(request, async_handler)
        assert result == "result"
