"""Tests for tool result registry (IG-433)."""

from soothe.config.models import ToolResultRegistryConfig
from soothe.foundation.loop.engine.tool_result_registry import (
    generate_outcome_metadata_v2,
    get_tool_result_registry,
)


class TestToolResultRegistry:
    def test_file_read_metadata(self) -> None:
        outcome = generate_outcome_metadata_v2(
            "read_file",
            "line1\nline2\n/path/to/file.py",
            "tc1",
            config=ToolResultRegistryConfig(enabled=True),
        )
        assert outcome["type"] == "file_read"
        assert outcome["size_bytes"] > 0

    def test_registry_parse_generic(self) -> None:
        registry = get_tool_result_registry()
        parsed = registry.parse("generic", "hello world")
        assert parsed["success_indicators"]["has_output"] is True
