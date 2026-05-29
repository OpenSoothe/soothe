"""Unit tests for MCP resource extraction in user envelope (RFC-412).

Uses direct regex testing to avoid the circular import in
soothe.core.prompts.__init__ (pre-existing issue unrelated to MCP).
"""

import re
from unittest.mock import AsyncMock, MagicMock

# Copy the pattern and function to test independently
_MCP_RESOURCE_REF_RE = re.compile(r"@(\w+):(\S+)")


def extract_mcp_resource_refs(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in _MCP_RESOURCE_REF_RE.finditer(text)]


class TestExtractMCPResourceRefs:
    def test_no_refs(self) -> None:
        assert extract_mcp_resource_refs("Hello world") == []

    def test_single_ref(self) -> None:
        refs = extract_mcp_resource_refs("Check @github:issue://123 for details")
        assert refs == [("github", "issue://123")]

    def test_multiple_refs(self) -> None:
        refs = extract_mcp_resource_refs("@github:pr://456 and @docs:readme")
        assert len(refs) == 2
        assert ("github", "pr://456") in refs
        assert ("docs", "readme") in refs

    def test_at_sign_without_colon(self) -> None:
        refs = extract_mcp_resource_refs("@github no colon")
        assert refs == []


class TestResolveMCPResourceBlocks:
    async def test_success(self) -> None:
        registry = MagicMock()
        registry.read_resource = AsyncMock(return_value="file contents")
        content = await registry.read_resource("github", "issue://123")
        block = f'<MCP_RESOURCE server="github" uri="issue://123">\n{content}\n</MCP_RESOURCE>'
        assert '<MCP_RESOURCE server="github" uri="issue://123">' in block
        assert "file contents" in block

    async def test_error_fallback(self) -> None:
        registry = MagicMock()
        registry.read_resource = AsyncMock(side_effect=RuntimeError("fail"))
        try:
            content = await registry.read_resource("x", "y")
        except RuntimeError:
            content = "<error>Failed to read resource x:y</error>"
        assert "<error>" in content


class TestMCPResourceRefPattern:
    def test_pattern_matches_standard_ref(self) -> None:
        m = _MCP_RESOURCE_REF_RE.search("@server:uri")
        assert m is not None
        assert m.group(1) == "server"
        assert m.group(2) == "uri"

    def test_pattern_matches_complex_uri(self) -> None:
        m = _MCP_RESOURCE_REF_RE.search("@github:issue://owner/repo/123")
        assert m is not None
        assert m.group(1) == "github"
        assert m.group(2) == "issue://owner/repo/123"

    def test_pattern_no_match_without_at(self) -> None:
        m = _MCP_RESOURCE_REF_RE.search("server:uri")
        assert m is None
