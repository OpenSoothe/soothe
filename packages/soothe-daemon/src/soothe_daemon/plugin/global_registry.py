"""Global plugin registry manager.

This module provides a singleton plugin registry that is initialized
during agent creation and accessed by resolvers.
"""

import logging
from typing import TYPE_CHECKING

from soothe_daemon.plugin.lifecycle import PluginLifecycleManager
from soothe_daemon.plugin.registry import PluginRegistry

if TYPE_CHECKING:
    from soothe_daemon.config.settings import SootheConfig

logger = logging.getLogger(__name__)

# Global plugin registry singleton
_global_registry: PluginRegistry | None = None
_global_lifecycle_manager: PluginLifecycleManager | None = None


def get_plugin_registry() -> PluginRegistry:
    """Get the global plugin registry.

    Raises:
        RuntimeError: If plugins have not been loaded yet.

    Returns:
        Global PluginRegistry instance.
    """
    if _global_registry is None:
        raise RuntimeError(
            "Plugin registry not initialized. Call load_plugins(config) during agent creation first."
        )
    return _global_registry


async def load_plugins(config: "SootheConfig") -> PluginRegistry:
    """Load all plugins and initialize the global registry.

    This should be called once during agent creation, before tool
    and subagent resolution.

    Args:
        config: Soothe configuration.

    Returns:
        Initialized PluginRegistry with all loaded plugins.
    """
    global _global_registry, _global_lifecycle_manager

    if _global_registry is not None:
        logger.warning("Plugins already loaded, returning existing registry")
        return _global_registry

    logger.info("Loading plugins...")

    # Create registry and lifecycle manager
    _global_registry = PluginRegistry()
    _global_lifecycle_manager = PluginLifecycleManager(_global_registry)

    # Load all plugins
    await _global_lifecycle_manager.load_all(config)

    logger.info(
        "Plugin loading complete: %d plugins, %d tools, %d subagents",
        len(_global_registry.list_all()),
        len(_global_registry.get_all_tools()),
        len(_global_registry.get_all_subagents()),
    )

    return _global_registry


async def shutdown_plugins() -> None:
    """Shutdown all loaded plugins.

    This should be called during agent cleanup.
    """
    global _global_registry, _global_lifecycle_manager

    if _global_lifecycle_manager:
        await _global_lifecycle_manager.shutdown_all()

    _global_registry = None
    _global_lifecycle_manager = None

    logger.info("Plugins shutdown complete")


def is_plugins_loaded() -> bool:
    """Check if plugins have been loaded.

    Returns:
        True if plugins are loaded, False otherwise.
    """
    return _global_registry is not None
