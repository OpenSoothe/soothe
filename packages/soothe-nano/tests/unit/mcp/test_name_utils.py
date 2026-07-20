"""Unit tests for MCP name utilities (RFC-412)."""

from soothe_nano.mcp.mcp_utils import (
    build_mcp_tool_name,
    is_mcp_tool_name,
    parse_mcp_tool_name,
)


class TestBuildMcpToolName:
    """Tests for build_mcp_tool_name."""

    def test_basic_name(self) -> None:
        """Basic server/tool combination."""
        result = build_mcp_tool_name("github", "create_issue")
        assert result == "mcp__github__create_issue"

    def test_special_chars_sanitized(self) -> None:
        """Special characters replaced with underscore."""
        result = build_mcp_tool_name("my-server", "tool-with-dashes")
        assert result == "mcp__my-server__tool-with-dashes"  # dashes allowed

        result = build_mcp_tool_name("my server", "tool name")
        assert result == "mcp__my_server__tool_name"  # spaces replaced

    def test_reserved_prefix(self) -> None:
        """All results start with reserved mcp__ prefix."""
        result = build_mcp_tool_name("any", "tool")
        assert result.startswith("mcp__")

    def test_empty_parts_invalid(self) -> None:
        """Empty server/tool still produces mangled name."""
        # Empty strings are valid inputs (just result in __ separator)
        result = build_mcp_tool_name("", "tool")
        assert result == "mcp____tool"


class TestParseMcpToolName:
    """Tests for parse_mcp_tool_name."""

    def test_valid_name(self) -> None:
        """Parse valid MCP tool name."""
        result = parse_mcp_tool_name("mcp__github__create_issue")
        assert result == ("github", "create_issue")

    def test_non_mcp_name(self) -> None:
        """Non-MCP name returns None."""
        assert parse_mcp_tool_name("read_file") is None
        assert parse_mcp_tool_name("builtin_tool") is None

    def test_missing_prefix(self) -> None:
        """Missing mcp__ prefix returns None."""
        assert parse_mcp_tool_name("github__create_issue") is None

    def test_malformed_name(self) -> None:
        """Malformed name (missing separator) returns None."""
        assert parse_mcp_tool_name("mcp__github") is None
        assert parse_mcp_tool_name("mcp__github_") is None  # single underscore

    def test_multiple_separators(self) -> None:
        """Multiple __ separators — first split determines server/tool."""
        result = parse_mcp_tool_name("mcp__server__tool__sub")
        assert result == ("server", "tool__sub")  # only first __ splits


class TestIsMcpToolName:
    """Tests for is_mcp_tool_name."""

    def test_mcp_prefix(self) -> None:
        """Name with mcp__ prefix returns True."""
        assert is_mcp_tool_name("mcp__server__tool") is True

    def test_non_mcp_prefix(self) -> None:
        """Name without mcp__ prefix returns False."""
        assert is_mcp_tool_name("server__tool") is False
        assert is_mcp_tool_name("read_file") is False

    def test_partial_prefix(self) -> None:
        """Partial prefix returns False."""
        assert is_mcp_tool_name("mcp_server__tool") is False
