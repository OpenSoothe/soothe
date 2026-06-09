"""Tool-specific result parsers for outcome metadata (IG-433)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from soothe.config.models import ToolResultRegistryConfig
from soothe.foundation.loop.engine import metadata_generator as _legacy_meta

logger = logging.getLogger(__name__)


class ToolResultParser(Protocol):
    """Parse a tool result into structured metadata fields."""

    def parse(self, result: Any) -> dict[str, Any]: ...

    def get_schema(self) -> dict[str, Any]: ...


@dataclass
class FileReadParser:
    """Parse file read tool results."""

    def parse(self, result: Any) -> dict[str, Any]:
        return _legacy_meta._extract_file_metadata(result)

    def get_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "success_indicators": {"type": "object"},
                "entities": {"type": "array"},
            },
        }


@dataclass
class FileWriteParser:
    """Parse file write tool results."""

    def parse(self, result: Any) -> dict[str, Any]:
        return _legacy_meta._extract_file_write_metadata(result)

    def get_schema(self) -> dict[str, Any]:
        return FileReadParser().get_schema()


@dataclass
class WebSearchParser:
    """Parse web search tool results."""

    def parse(self, result: Any) -> dict[str, Any]:
        return _legacy_meta._extract_search_metadata(result)

    def get_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"success_indicators": {"type": "object"}}}


@dataclass
class CodeExecParser:
    """Parse shell/code execution results using exit-code patterns."""

    def parse(self, result: Any) -> dict[str, Any]:
        return _legacy_meta._extract_exec_metadata(result)

    def get_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"success_indicators": {"type": "object"}}}


@dataclass
class SubagentParser:
    """Parse subagent task delegation results."""

    def parse(self, result: Any) -> dict[str, Any]:
        return _legacy_meta._extract_subagent_metadata(result)

    def get_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"success_indicators": {"type": "object"}}}


@dataclass
class GenericParser:
    """Fallback parser for unknown tool types."""

    def parse(self, result: Any) -> dict[str, Any]:
        return _legacy_meta._extract_generic_metadata(result)

    def get_schema(self) -> dict[str, Any]:
        return {"type": "object"}


_DEFAULT_PARSERS: dict[str, ToolResultParser] = {
    "file_read": FileReadParser(),
    "file_write": FileWriteParser(),
    "web_search": WebSearchParser(),
    "code_exec": CodeExecParser(),
    "subagent": SubagentParser(),
    "generic": GenericParser(),
}


class ToolResultRegistry:
    """Registry of outcome-type-specific parsers."""

    def __init__(self) -> None:
        self._parsers: dict[str, ToolResultParser] = dict(_DEFAULT_PARSERS)

    def register(self, outcome_type: str, parser: ToolResultParser) -> None:
        """Register or replace a parser for an outcome type."""
        self._parsers[outcome_type] = parser

    def parse(self, outcome_type: str, result: Any) -> dict[str, Any]:
        """Parse tool result using the registered parser."""
        parser = self._parsers.get(outcome_type) or self._parsers["generic"]
        return parser.parse(result)

    def get_schema(self, outcome_type: str) -> dict[str, Any]:
        """Return JSON schema for parser output."""
        parser = self._parsers.get(outcome_type) or self._parsers["generic"]
        return parser.get_schema()


_registry: ToolResultRegistry | None = None


def get_tool_result_registry() -> ToolResultRegistry:
    """Return shared tool result registry."""
    global _registry
    if _registry is None:
        _registry = ToolResultRegistry()
    return _registry


def generate_outcome_metadata_v2(
    tool_name: str,
    result: Any,
    tool_call_id: str,
    *,
    config: ToolResultRegistryConfig | None = None,
) -> dict[str, Any]:
    """Generate outcome metadata via registry with legacy fallback."""
    from soothe_sdk.utils import get_outcome_type

    cfg = config or ToolResultRegistryConfig()
    outcome_type = get_outcome_type(tool_name)

    if cfg.enabled:
        registry = get_tool_result_registry()
        try:
            parsed = registry.parse(outcome_type, result)
        except Exception:
            logger.debug("Tool result registry parse failed for %s", outcome_type)
            parsed = {}  # Skip regex fallback, return minimal metadata
    else:
        return _legacy_meta.generate_outcome_metadata(tool_name, result, tool_call_id)

    content_str = result if isinstance(result, str) else str(result)
    return {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "type": outcome_type,
        **parsed,
        "size_bytes": len(content_str.encode("utf-8")),
    }
