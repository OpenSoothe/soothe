"""Plugin lifecycle management.

This module provides the PluginLifecycleManager that orchestrates the complete
plugin lifecycle from discovery through initialization to shutdown.
"""

import logging
from typing import TYPE_CHECKING, Any

from soothe.plugin.context import create_plugin_context
from soothe.plugin.discovery import discover_all_plugins
from soothe.plugin.events import PluginFailedEvent, PluginLoadedEvent, PluginUnloadedEvent
from soothe.plugin.exceptions import InitializationError
from soothe.plugin.loader import PluginLoader
from soothe.utils.progress import emit_progress

if TYPE_CHECKING:
    from soothe.config.settings import SootheConfig
    from soothe.plugin.registry import PluginRegistry

logger = logging.getLogger(__name__)


class PluginLifecycleManager:
    """Manage the complete plugin lifecycle.

    This class orchestrates all phases of plugin management:
    1. Discovery - Find plugins from all sources
    2. Loading - Import and instantiate plugins
    3. Initialization - Call on_load() hooks
    4. Registration - Register tools and subagents
    5. Shutdown - Call on_unload() hooks

    Attributes:
        registry: Plugin registry for storing loaded plugins.
        loader: Plugin loader for dependency resolution and instantiation.
        loaded_plugins: Dict of successfully loaded plugin instances.
    """

    def __init__(self, registry: "PluginRegistry") -> None:
        """Initialize lifecycle manager.

        Args:
            registry: Plugin registry to register loaded plugins.
        """
        self.registry = registry
        self.loader = PluginLoader(registry)
        self.loaded_plugins: dict[str, Any] = {}

    async def load_all(self, config: "SootheConfig") -> dict[str, Any]:
        """Load all discovered plugins.

        This is the main entry point for plugin loading. It:
        1. Discovers plugins from all sources
        2. Loads and validates each plugin
        3. Calls on_load() hooks
        4. Registers tools and subagents
        5. Emits lifecycle events

        Args:
            config: Soothe configuration.

        Returns:
            Dict mapping plugin names to loaded instances.
        """
        logger.info("Starting plugin discovery and loading...")

        # Phase 1: Discovery
        discovered = discover_all_plugins(config)
        logger.info("Discovered %s plugins", len(discovered))

        # Phase 2: Load each plugin
        for module_path, plugin_config in discovered.values():
            await self._load_single_plugin(module_path, config, plugin_config)

        logger.info("Successfully loaded %s plugins", len(self.loaded_plugins))
        return self.loaded_plugins

    async def shutdown_all(self) -> None:
        """Shutdown all loaded plugins.

        Calls on_unload() hooks for all loaded plugins and emits
        unloading events.
        """
        logger.info("Shutting down plugins...")

        for name, plugin_instance in self.loaded_plugins.items():
            try:
                # Call on_unload hook if it exists
                if hasattr(plugin_instance, "on_unload"):
                    await plugin_instance.on_unload()

                # Emit unloading event
                emit_progress(PluginUnloadedEvent(name=name).model_dump(), logger)

                logger.info("Shutdown plugin '%s'", name)

            except Exception:
                logger.exception("Failed to shutdown plugin '%s'", name)

        self.loaded_plugins.clear()

    async def _load_single_plugin(
        self,
        module_path: str,
        config: "SootheConfig",
        plugin_config: dict[str, Any],
    ) -> None:
        """Load a single plugin from module path.

        Args:
            module_path: Python import path.
            config: Soothe configuration.
            plugin_config: Plugin-specific configuration.
        """
        try:
            # Load plugin instance
            plugin_instance = self.loader.load_plugin(module_path, config, plugin_config)

            # Get manifest
            manifest = plugin_instance.manifest
            name = manifest.name

            # Create plugin context
            context = create_plugin_context(
                plugin_name=name,
                config=plugin_config,
                soothe_config=config,
                emit_event_callback=lambda n, d: emit_progress({**d, "type": n}, logger),
            )

            # Call on_load hook
            if hasattr(plugin_instance, "on_load"):
                try:
                    await plugin_instance.on_load(context)
                except Exception as e:
                    msg = f"on_load() hook failed: {e}"
                    raise InitializationError(
                        msg,
                        plugin_name=name,
                    ) from e

            # Extract tools and subagents
            tools = self._extract_tools(plugin_instance)
            subagents = self._extract_subagents(plugin_instance)

            # Update registry entry
            entry = self.registry.get(name)
            if entry:
                entry.plugin_instance = plugin_instance
                entry.tools = tools
                entry.subagents = subagents

            # Store in loaded plugins
            self.loaded_plugins[name] = plugin_instance

            # Emit loaded event
            emit_progress(
                PluginLoadedEvent(
                    name=name,
                    version=manifest.version,
                    source=entry.source if entry else "unknown",
                ).model_dump(),
                logger,
            )

            logger.info(
                "Loaded plugin '%s' v%s (%d tools, %d subagents)",
                name,
                manifest.version,
                len(tools),
                len(subagents),
            )

        except Exception as e:
            # Determine plugin name for error reporting
            plugin_name = ""
            if "plugin_instance" in locals() and hasattr(plugin_instance, "manifest"):
                plugin_name = plugin_instance.manifest.name

            # Emit failed event
            phase = "initialization" if "InitializationError" in str(type(e)) else "loading"
            emit_progress(
                PluginFailedEvent(
                    name=plugin_name,
                    error=str(e),
                    phase=phase,
                ).model_dump(),
                logger,
            )

            logger.exception("Failed to load plugin from %s", module_path)

    def _extract_tools(self, plugin_instance: Any) -> list[Any]:
        """Extract tools from a plugin instance.

        Uses the get_tools() method added by the @plugin decorator.

        Args:
            plugin_instance: Loaded plugin instance.

        Returns:
            List of tool functions with _is_tool metadata.
        """
        if hasattr(plugin_instance, "get_tools"):
            return plugin_instance.get_tools()
        return []

    def _extract_subagents(self, plugin_instance: Any) -> list[Any]:
        """Extract subagent factories from a plugin instance.

        Uses the get_subagents() method added by the @plugin decorator.

        Args:
            plugin_instance: Loaded plugin instance.

        Returns:
            List of subagent factory functions with _is_subagent metadata.
        """
        if hasattr(plugin_instance, "get_subagents"):
            return plugin_instance.get_subagents()
        return []
