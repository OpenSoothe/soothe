"""Plugin registry with priority-based conflict resolution.

This module provides the PluginRegistry class that stores discovered plugins
and resolves conflicts based on source priority.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from soothe_sdk.types.manifest import PluginManifest

logger = logging.getLogger(__name__)


@dataclass
class RegistryEntry:
    """Entry in the plugin registry.

    Attributes:
        manifest: Plugin manifest with metadata.
        source: Discovery source (built-in, entry_point, config, filesystem).
        priority: Priority level (higher = preferred).
        plugin_instance: Loaded plugin instance (None until loaded).
        tools: List of langchain BaseTool instances provided by this plugin.
        subagents: List of subagent factory functions provided by this plugin.
    """

    manifest: PluginManifest
    source: Literal["built-in", "entry_point", "config", "filesystem"]
    priority: int
    plugin_instance: Any = None
    tools: list[Any] = field(default_factory=list)
    subagents: list[Any] = field(default_factory=list)


class PluginRegistry:
    """Registry for discovered plugins with priority-based conflict resolution.

    The registry stores all discovered plugins and resolves conflicts when
    multiple sources provide plugins with the same name. Priority ordering:
    built-in (100) > entry_point (50) > config (30) > filesystem (10).

    Attributes:
        PRIORITY_BUILTIN: Priority for built-in plugins (100).
        PRIORITY_ENTRY_POINT: Priority for entry point plugins (50).
        PRIORITY_CONFIG: Priority for config-declared plugins (30).
        PRIORITY_FILESYSTEM: Priority for filesystem-discovered plugins (10).
    """

    PRIORITY_BUILTIN = 100
    PRIORITY_ENTRY_POINT = 50
    PRIORITY_CONFIG = 30
    PRIORITY_FILESYSTEM = 10

    def __init__(self) -> None:
        """Initialize empty plugin registry."""
        self._plugins: dict[str, RegistryEntry] = {}

    def register(
        self,
        manifest: PluginManifest,
        source: Literal["built-in", "entry_point", "config", "filesystem"],
        priority: int | None = None,
    ) -> None:
        """Register a plugin manifest with source and priority.

        If a plugin with the same name already exists, the one with higher
        priority wins. If priorities are equal, the existing one is kept.

        Args:
            manifest: Plugin manifest with metadata.
            source: Discovery source.
            priority: Optional priority override. If None, uses default for source.
        """
        if priority is None:
            priority = {
                "built-in": self.PRIORITY_BUILTIN,
                "entry_point": self.PRIORITY_ENTRY_POINT,
                "config": self.PRIORITY_CONFIG,
                "filesystem": self.PRIORITY_FILESYSTEM,
            }[source]

        existing = self._plugins.get(manifest.name)
        if existing and existing.priority >= priority:
            logger.warning(
                "Ignoring duplicate plugin '%s' from %s (existing has priority %d >= %d)",
                manifest.name,
                source,
                existing.priority,
                priority,
            )
            return

        self._plugins[manifest.name] = RegistryEntry(
            manifest=manifest,
            source=source,
            priority=priority,
        )
        logger.info(
            "Registered plugin '%s' v%s from %s (priority=%d)",
            manifest.name,
            manifest.version,
            source,
            priority,
        )

    def get(self, name: str) -> RegistryEntry | None:
        """Get registry entry by plugin name.

        Args:
            name: Plugin name.

        Returns:
            Registry entry if found, None otherwise.
        """
        return self._plugins.get(name)

    def list_all(self) -> list[RegistryEntry]:
        """List all registered entries.

        Returns:
            List of all registry entries.
        """
        return list(self._plugins.values())

    def get_all_tools(self) -> list[Any]:
        """Get all registered tools from all plugins.

        Returns:
            List of all langchain BaseTool instances from all loaded plugins.
        """
        tools = []
        for entry in self._plugins.values():
            if entry.tools:
                tools.extend(entry.tools)
        return tools

    def get_all_subagents(self) -> list[Any]:
        """Get all registered subagent factories from all plugins.

        Returns:
            List of all subagent factory functions from all loaded plugins.
        """
        subagents = []
        for entry in self._plugins.values():
            if entry.subagents:
                subagents.extend(entry.subagents)
        return subagents

    def get_tools_for_group(self, group_name: str) -> list[Any]:
        """Get tools for a specific tool group.

        Args:
            group_name: Tool group name (e.g., "execution", "file_ops").

        Returns:
            List of tools for the group, or empty list if not found.
        """
        # Look for a plugin whose name matches the group name
        entry = self._plugins.get(group_name)
        if entry and entry.tools:
            return entry.tools

        # Search for tools with matching group metadata
        return [
            tool
            for entry in self._plugins.values()
            for tool in entry.tools
            if hasattr(tool, "_tool_group") and tool._tool_group == group_name
        ]

    def get_subagent_factory(self, name: str) -> Any | None:
        """Get subagent factory function by name.

        Args:
            name: Subagent name.

        Returns:
            Subagent factory function if found, None otherwise.
        """
        # Search all plugins for a subagent with this name
        for entry in self._plugins.values():
            for factory in entry.subagents:
                if hasattr(factory, "_subagent_name") and factory._subagent_name == name:
                    return factory

        return None

    def get_subagent_default_config(self, name: str) -> dict[str, Any]:
        """Get default config for a plugin subagent.

        Args:
            name: Subagent name.

        Returns:
            Default config dict (empty if not found or no default config).
        """
        factory = self.get_subagent_factory(name)
        if factory and hasattr(factory, "_subagent_default_config"):
            return factory._subagent_default_config
        return {}

    def list_subagent_names(self) -> list[str]:
        """List all registered subagent names from plugins.

        Returns:
            List of subagent names.
        """
        return [
            factory._subagent_name
            for entry in self._plugins.values()
            for factory in entry.subagents
            if hasattr(factory, "_subagent_name")
        ]

    def clear(self) -> None:
        """Clear all registered plugins.

        Used for testing and cleanup.
        """
        self._plugins.clear()
