"""MCP tool name mangling utilities (RFC-412).

Mirrors Claude Code's mcpStringUtils.ts: buildMcpToolName() and normalization logic.
Coordinates with langchain_mcp_adapters' tool_name_prefix=False setting.
"""

from __future__ import annotations

import re

# Pattern for sanitizing: keep only a-zA-Z0-9_-
_SANITIZE_PATTERN = re.compile(r"[^a-zA-Z0-9_-]")

# Reserved prefix for MCP tools
MCP_PREFIX = "mcp__"


def _sanitize(name: str) -> str:
    """Sanitize a name for MCP tool/prompt naming.

    Replaces non-[a-zA-Z0-9_-] chars with underscore.
    """
    return _SANITIZE_PATTERN.sub("_", name)


def build_mcp_tool_name(server: str, tool: str) -> str:
    """Build mangled MCP tool name: mcp__<sanitized_server>__<sanitized_tool>.

    Args:
        server: MCP server name (from MCPServerConfig.name).
        tool: Bare tool name from the MCP server's tools/list response.

    Returns:
        Mangled name with reserved 'mcp__' prefix.

    Note:
        langchain_mcp_adapters is initialized with tool_name_prefix=False,
        so soothe controls the prefix convention entirely. The 'mcp__' prefix
        is reserved and cannot be used by built-in soothe tools.
    """
    sanitized_server = _sanitize(server)
    sanitized_tool = _sanitize(tool)
    return f"{MCP_PREFIX}{sanitized_server}__{sanitized_tool}"


def parse_mcp_tool_name(name: str) -> tuple[str, str] | None:
    """Parse mangled name into (server, bare_tool).

    Args:
        name: Potentially mangled MCP tool name.

    Returns:
        Tuple of (server, bare_tool) if name is an MCP tool, else None.
        Returns None if the name doesn't start with 'mcp__' or is malformed.
    """
    if not name.startswith(MCP_PREFIX):
        return None

    remainder = name[len(MCP_PREFIX) :]
    parts = remainder.split("__", 1)
    if len(parts) != 2:
        return None

    server, tool = parts
    if not server or not tool:
        return None

    return (server, tool)


def is_mcp_tool_name(name: str) -> bool:
    """Check if a name is an MCP tool name (starts with 'mcp__')."""
    return name.startswith(MCP_PREFIX)
