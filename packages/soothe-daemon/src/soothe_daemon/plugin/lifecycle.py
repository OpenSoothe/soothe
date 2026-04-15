"""Plugin lifecycle management.

This module provides the PluginLifecycleManager that orchestrates the complete
plugin lifecycle from discovery through initialization to shutdown.
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from soothe_daemon.plugin.cache import cache_plugin, get_cached_plugin
from soothe_daemon.plugin.context import create_plugin_context
from soothe_daemon.plugin.discovery import discover_all_plugins
from soothe_daemon.plugin.events import (
    PluginFailedEvent,
    PluginHealthCheckedEvent,
    PluginLoadedEvent,
    PluginUnloadedEvent,
)
from soothe_daemon.plugin.exceptions import InitializationError
from soothe_daemon.plugin.loader import PluginLoader
from soothe_daemon.utils.progress import emit_progress

if TYPE_CHECKING:
    from soothe_daemon.config.settings import SootheConfig
    from soothe_daemon.plugin.registry import PluginRegistry

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

    async def load_all(
        self,
        config: "SootheConfig",
        lazy_plugins: list[str] | None = None,
    ) -> dict[str, Any]:
        """Load all discovered plugins with parallel loading.

        This is the main entry point for plugin loading. It:
        1. Discovers plugins from all sources
        2. Loads and validates each plugin in parallel
        3. Calls on_load() hooks
        4. Registers tools and subagents
        5. Emits lifecycle events

        Args:
            config: Soothe configuration.
            lazy_plugins: Optional list of plugin names to load lazily.

        Returns:
            Dict mapping plugin names to loaded instances.
        """
        logger.info("Starting plugin discovery and loading...")

        # Phase 1: Discovery
        discovered = discover_all_plugins(config)
        logger.info("Discovered %s plugins", len(discovered))

        # Phase 2: Build dependency graph
        dependency_graph = self._build_dependency_graph(discovered)

        # Phase 3: Load plugins in parallel respecting dependencies
        await self._load_plugins_parallel(
            dependency_graph,
            discovered,
            config,
            lazy_plugins=lazy_plugins,
        )

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

    async def health_check_all(self) -> dict[str, dict]:
        """Run health checks on all loaded plugins.

        Calls the health_check() hook on each loaded plugin and
        emits health check events.

        Returns:
            Dict mapping plugin names to their health status dicts.
        """
        results: dict[str, dict] = {}

        for name, plugin_instance in list(self.loaded_plugins.items()):
            try:
                if hasattr(plugin_instance, "health_check"):
                    result = await plugin_instance.health_check()
                    if hasattr(result, "model_dump"):
                        status = result.model_dump()
                    elif isinstance(result, dict):
                        status = result
                    else:
                        status = {"status": "healthy", "details": str(result)}
                else:
                    status = {"status": "healthy", "details": "No health_check() method"}

                status_value = status.get("status", "healthy")
                if status_value not in ("healthy", "degraded", "unhealthy"):
                    status_value = "degraded"

                emit_progress(
                    PluginHealthCheckedEvent(
                        name=name,
                        status=status_value,
                        details=status.get("details", ""),
                    ).model_dump(),
                    logger,
                )
            except Exception as e:
                status = {"status": "unhealthy", "details": str(e)}
                logger.exception("Health check failed for plugin '%s'", name)
                emit_progress(
                    PluginHealthCheckedEvent(
                        name=name,
                        status="unhealthy",
                        details=str(e),
                    ).model_dump(),
                    logger,
                )

            results[name] = status

        return results

    def _build_dependency_graph(
        self,
        discovered: dict[str, tuple[str, dict]],
    ) -> dict[str, set[str]]:
        """Build plugin dependency graph from manifests.

        Args:
            discovered: Discovered plugins dict mapping name to (module_path, config).

        Returns:
            Dict mapping plugin name to set of dependency names.
        """
        graph: dict[str, set[str]] = {}

        for plugin_name in discovered:
            # Try to load manifest to check dependencies
            try:
                # For now, assume no dependencies for built-in plugins
                # This can be enhanced later to read from plugin manifest
                graph[plugin_name] = set()
            except Exception:
                logger.debug(
                    "Could not load manifest for plugin '%s', assuming no dependencies",
                    plugin_name,
                )
                graph[plugin_name] = set()

        return graph

    async def _load_plugins_parallel(
        self,
        graph: dict[str, set[str]],
        discovered: dict[str, tuple[str, dict]],
        config: "SootheConfig",
        lazy_plugins: list[str] | None = None,
    ) -> None:
        """Load plugins in parallel respecting dependencies.

        Args:
            graph: Dependency graph mapping plugin name to dependencies.
            discovered: Discovered plugins dict.
            config: Soothe configuration.
            lazy_plugins: Plugins to load lazily.
        """
        loaded: set[str] = set()
        lazy_plugins_set = set(lazy_plugins or [])

        while len(loaded) < len(graph):
            # Find plugins with all dependencies satisfied
            ready = [
                name for name, deps in graph.items() if name not in loaded and deps.issubset(loaded)
            ]

            if not ready:
                # Circular dependency or missing dependency
                remaining = set(graph.keys()) - loaded
                logger.error(
                    "Cannot resolve dependencies for plugins: %s",
                    remaining,
                )
                break

            # Separate eager and lazy plugins
            eager = [name for name in ready if name not in lazy_plugins_set]
            lazy = [name for name in ready if name in lazy_plugins_set]

            # Load eager plugins in parallel
            if eager:
                tasks = [
                    self._load_single_plugin(
                        discovered[name][0],
                        config,
                        discovered[name][1],
                    )
                    for name in eager
                ]
                await asyncio.gather(*tasks, return_exceptions=True)
                loaded.update(eager)

            # Create lazy proxies for lazy plugins
            for name in lazy:
                from soothe_daemon.plugin.lazy import LazyPlugin

                def loader(n: str = name) -> Any:
                    # Sync loader for lazy plugin
                    return self.loader.load_plugin(
                        discovered[n][0],
                        config,
                        discovered[n][1],
                    )

                lazy_proxy = LazyPlugin(name, loader)
                cache_plugin(name, lazy_proxy)
                self.loaded_plugins[name] = lazy_proxy
                loaded.add(name)
                logger.info("Created lazy proxy for plugin '%s'", name)

    async def _load_single_plugin(
        self,
        module_path: str,
        config: "SootheConfig",
        plugin_config: dict[str, Any],
    ) -> None:
        """Load a single plugin from module path with caching.

        Args:
            module_path: Python import path.
            config: Soothe configuration.
            plugin_config: Plugin-specific configuration.
        """
        # Extract plugin name from module_path for caching
        plugin_name_guess = (
            module_path.rsplit(".", maxsplit=1)[-1]
            if "." in module_path
            else module_path.split(":", maxsplit=1)[0]
        )

        # Check cache first
        cached = get_cached_plugin(plugin_name_guess)
        if cached:
            logger.debug("Using cached plugin '%s'", plugin_name_guess)
            self.loaded_plugins[plugin_name_guess] = cached
            return

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

            # Cache the loaded plugin
            cache_plugin(name, plugin_instance)

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
