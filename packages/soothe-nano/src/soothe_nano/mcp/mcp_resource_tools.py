"""Synthetic MCP tools for resource listing and reading.

These tools are injected into the model tool catalog so resource discovery
and reads follow the same execution flow as ordinary tools.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from soothe_nano.mcp.mcp_registry import MCPRegistry


class _ListResourcesInput(BaseModel):
    """Input schema for mcp_resources_list."""

    server: str | None = Field(
        default=None,
        description="MCP server name to filter by. Omit to list all servers.",
    )


class _ReadResourceInput(BaseModel):
    """Input schema for mcp_resources_read."""

    server: str = Field(description="MCP server name")
    uri: str = Field(description="Resource URI to read")


def _format_resource_list(
    all_resources: dict[str, list[dict]],
    server_filter: str | None = None,
) -> str:
    """Format resource descriptors as human-readable text."""
    lines: list[str] = []
    for server_name, resources in all_resources.items():
        if server_filter and server_name != server_filter:
            continue
        lines.append(f"## {server_name}")
        if not resources:
            lines.append("  (no resources)")
            continue
        for resource in resources:
            name = resource.get("name") or resource.get("uri", "?")
            desc = resource.get("description") or ""
            mime = resource.get("mime_type") or ""
            line = f"  - {name}"
            if desc:
                line += f": {desc}"
            if mime:
                line += f" [{mime}]"
            lines.append(line)
    return "\n".join(lines) if lines else "No MCP resources available."


def mcp_resources_list_tool(registry: MCPRegistry) -> StructuredTool:
    """Create a synthetic tool that lists available MCP resources."""

    async def _list(server: str | None = None) -> str:
        try:
            all_resources = registry.resources()
        except Exception as error:  # noqa: BLE001
            return f"Error listing resources: {error}"
        return _format_resource_list(all_resources, server)

    return StructuredTool.from_function(
        coroutine=_list,
        name="mcp_resources_list",
        description=(
            "List available MCP resources from connected servers. Optionally filter by server name."
        ),
        args_schema=_ListResourcesInput,
    )


def mcp_resources_read_tool(registry: MCPRegistry) -> StructuredTool:
    """Create a synthetic tool that reads an MCP resource."""

    async def _read(server: str, uri: str) -> str:
        try:
            content = await registry.read_resource(server, uri)
        except Exception as error:  # noqa: BLE001
            return f"Error reading resource: {error}"
        return str(content)

    return StructuredTool.from_function(
        coroutine=_read,
        name="mcp_resources_read",
        description=(
            "Read an MCP resource by server name and URI. "
            "Use mcp_resources_list to discover available resources."
        ),
        args_schema=_ReadResourceInput,
    )


def create_mcp_resource_tools(registry: MCPRegistry) -> list[StructuredTool]:
    """Create both MCP resource tools for injection into the agent."""
    return [mcp_resources_list_tool(registry), mcp_resources_read_tool(registry)]
