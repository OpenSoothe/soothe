"""Tool caching utilities for resolved tool groups.

Provides an in-process LRU-style cache so that tool groups resolved once
(whether sequentially or via parallel ``ThreadPoolExecutor``) are reused
on subsequent lookups without re-importing or re-constructing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

_tool_cache: dict[str, list[BaseTool]] = {}


def get_cached_tools(tool_name: str) -> list[BaseTool] | None:
    """Get tools from cache if available.

    Args:
        tool_name: Name of the tool group.

    Returns:
        Cached tools or None if not cached.
    """
    return _tool_cache.get(tool_name)


def cache_tools(tool_name: str, tools: list[BaseTool]) -> None:
    """Cache a tool group for reuse.

    Args:
        tool_name: Name of the tool group.
        tools: List of tools to cache.
    """
    _tool_cache[tool_name] = tools
    logger.debug("Cached tool group '%s' (%d tools)", tool_name, len(tools))


def clear_tool_cache() -> None:
    """Clear the tool cache."""
    global _tool_cache
    _tool_cache = {}
    logger.debug("Tool cache cleared")


def get_cache_stats() -> dict[str, Any]:
    """Get tool cache statistics.

    Returns:
        Dictionary with cache statistics.
    """
    return {
        "cached_groups": len(_tool_cache),
        "total_tools": sum(len(tools) for tools in _tool_cache.values()),
        "groups": list(_tool_cache.keys()),
    }
