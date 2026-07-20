"""Unit tests for MCP synthetic tools (RFC-412)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_nano.mcp.mcp_resource_tools import (
    _format_resource_list,
    create_mcp_resource_tools,
    mcp_resources_list_tool,
    mcp_resources_read_tool,
)


@pytest.fixture
def mock_registry() -> MagicMock:
    """Create a mock MCPRegistry."""
    reg = MagicMock()
    reg.resources.return_value = {
        "github": [
            {
                "uri": "issue://123",
                "name": "Issue 123",
                "description": "A GitHub issue",
                "server": "github",
                "mime_type": "text/plain",
            },
        ],
        "docs": [],
    }
    reg.read_resource = AsyncMock(return_value="resource content")
    return reg


class TestFormatResourceList:
    def test_all_servers(self) -> None:
        resources = {
            "github": [
                {
                    "name": "Issue 123",
                    "uri": "issue://123",
                    "description": "A bug",
                    "mime_type": "text/plain",
                },
            ],
            "docs": [],
        }
        result = _format_resource_list(resources)
        assert "github" in result
        assert "Issue 123" in result
        assert "docs" in result
        assert "no resources" in result

    def test_server_filter(self) -> None:
        resources = {
            "github": [{"name": "X", "uri": "x", "description": "", "mime_type": ""}],
            "docs": [{"name": "Y", "uri": "y", "description": "", "mime_type": ""}],
        }
        result = _format_resource_list(resources, server_filter="github")
        assert "github" in result
        assert "docs" not in result

    def test_empty(self) -> None:
        result = _format_resource_list({})
        assert "No MCP resources" in result


class TestMCPResourcesListTool:
    async def test_list_all(self, mock_registry: MagicMock) -> None:
        tool = mcp_resources_list_tool(mock_registry)
        result = await tool.ainvoke({"server": None})
        assert "github" in result
        assert "Issue 123" in result

    async def test_list_filtered(self, mock_registry: MagicMock) -> None:
        tool = mcp_resources_list_tool(mock_registry)
        result = await tool.ainvoke({"server": "github"})
        assert "github" in result

    async def test_list_error(self) -> None:
        reg = MagicMock()
        reg.resources.side_effect = RuntimeError("not initialized")
        tool = mcp_resources_list_tool(reg)
        result = await tool.ainvoke({"server": None})
        assert "Error" in result


class TestMCPResourcesReadTool:
    async def test_read_success(self, mock_registry: MagicMock) -> None:
        tool = mcp_resources_read_tool(mock_registry)
        result = await tool.ainvoke({"server": "github", "uri": "issue://123"})
        assert "resource content" in result

    async def test_read_error(self) -> None:
        reg = MagicMock()
        reg.read_resource = AsyncMock(side_effect=ValueError("not found"))
        tool = mcp_resources_read_tool(reg)
        result = await tool.ainvoke({"server": "x", "uri": "y"})
        assert "Error" in result


class TestCreateMCPResourceTools:
    def test_returns_two_tools(self, mock_registry: MagicMock) -> None:
        tools = create_mcp_resource_tools(mock_registry)
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"mcp_resources_list", "mcp_resources_read"}
