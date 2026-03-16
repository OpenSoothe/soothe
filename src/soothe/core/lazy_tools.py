"""Lazy loading framework for tools and subagents.

This module provides lazy loading capabilities to defer expensive
initialization until components are actually needed.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


class LazyToolProxy:
    """Proxy that defers tool initialization until first use.

    This wraps a tool loader function and only calls it when the tool
    is actually needed, reducing startup time for unused tools.
    """

    def __init__(self, tool_name: str, loader: Callable[[], list[BaseTool]], index: int = 0) -> None:
        """Initialize lazy tool proxy.

        Args:
            tool_name: Name of the tool group.
            loader: Function that returns a list of tools.
            index: Index within the tool list to use.
        """
        self._tool_name = tool_name
        self._loader = loader
        self._index = index
        self._tool: BaseTool | None = None
        self._loaded = False

    def _ensure_loaded(self) -> BaseTool:
        """Load the tool if not already loaded."""
        if not self._loaded:
            start = time.perf_counter()
            try:
                tools = self._loader()
                if tools and len(tools) > self._index:
                    self._tool = tools[self._index]
                else:
                    logger.warning(
                        "Tool group '%s' returned %d tools, index %d out of range",
                        self._tool_name,
                        len(tools) if tools else 0,
                        self._index,
                    )
            except Exception:
                logger.exception("Failed to lazy-load tool '%s'", self._tool_name)
                raise

            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.debug(
                "Lazy-loaded tool '%s' in %.1fms",
                self._tool_name,
                elapsed_ms,
            )
            self._loaded = True

        if self._tool is None:
            msg = f"Tool '{self._tool_name}' could not be loaded"
            raise RuntimeError(msg)

        return self._tool

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the actual tool."""
        if name.startswith("_"):
            # Don't proxy private attributes
            msg = f"'{type(self).__name__}' object has no attribute '{name}'"
            raise AttributeError(msg)
        return getattr(self._ensure_loaded(), name)

    def __repr__(self) -> str:
        """Return representation."""
        if self._loaded:
            return f"LazyToolProxy({self._tool_name}, loaded={self._tool})"
        return f"LazyToolProxy({self._tool_name}, loaded=False)"


class LazySubagentSpec:
    """Subagent spec that defers initialization until first use.

    This wraps a subagent factory and only creates the instance when
    needed, reducing startup time for unused subagents.
    """

    def __init__(self, name: str, factory: Callable, kwargs: dict[str, Any]) -> None:
        """Initialize lazy subagent spec.

        Args:
            name: Subagent name.
            factory: Factory function to create the subagent.
            kwargs: Keyword arguments for the factory.
        """
        self.name = name
        self._factory = factory
        self._kwargs = kwargs
        self._instance = None
        self._loaded = False

    def get_instance(self) -> Any:
        """Get the subagent instance, creating it if needed."""
        if not self._loaded:
            start = time.perf_counter()
            try:
                self._instance = self._factory(**self._kwargs)
            except Exception:
                logger.exception("Failed to lazy-load subagent '%s'", self.name)
                raise

            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "Lazy-loaded subagent '%s' in %.1fms",
                self.name,
                elapsed_ms,
            )
            self._loaded = True

        return self._instance

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the actual subagent."""
        if name.startswith("_"):
            # Don't proxy private attributes
            msg = f"'{type(self).__name__}' object has no attribute '{name}'"
            raise AttributeError(msg)
        return getattr(self.get_instance(), name)

    def __contains__(self, key: str) -> bool:
        """Check if key is in the subagent spec (for dict-like access)."""
        # When checking if "runnable" in spec, we need to check the actual spec dict
        instance = self.get_instance()
        if isinstance(instance, dict):
            return key in instance
        # Fallback for non-dict instances
        return hasattr(instance, key)

    def __getitem__(self, key: str) -> Any:
        """Get item from subagent spec (for dict-like access)."""
        instance = self.get_instance()
        if isinstance(instance, dict):
            return instance[key]
        # Fallback for non-dict instances
        return getattr(instance, key)

    def get(self, key: str, default: Any = None) -> Any:
        """Get item from subagent spec with default value."""
        try:
            return self[key]
        except (KeyError, AttributeError):
            return default

    def keys(self) -> Any:
        """Return keys of the subagent spec."""
        instance = self.get_instance()
        if isinstance(instance, dict):
            return instance.keys()
        # Fallback for non-dict instances
        return [k for k in dir(instance) if not k.startswith("_")]

    def values(self) -> Any:
        """Return values of the subagent spec."""
        instance = self.get_instance()
        if isinstance(instance, dict):
            return instance.values()
        # Fallback for non-dict instances
        return [getattr(instance, k) for k in self.keys()]

    def items(self) -> Any:
        """Return items of the subagent spec."""
        instance = self.get_instance()
        if isinstance(instance, dict):
            return instance.items()
        # Fallback for non-dict instances
        return [(k, getattr(instance, k)) for k in self.keys()]

    def __iter__(self) -> Any:
        """Iterate over keys."""
        return iter(self.keys())

    def __repr__(self) -> str:
        """Return representation."""
        if self._loaded:
            return f"LazySubagentSpec({self.name}, loaded={type(self._instance).__name__})"
        return f"LazySubagentSpec({self.name}, loaded=False)"


# Tool cache for reusing loaded tool groups
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
