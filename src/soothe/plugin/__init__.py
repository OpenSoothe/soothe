"""Soothe Plugin System.

This package provides the core plugin infrastructure for Soothe, enabling
third-party developers to create custom tools and subagents using the
decorator-based API in soothe_sdk.

Key Components:
- PluginRegistry: Priority-based storage with conflict resolution
- PluginLoader: Dependency resolution and instantiation
- PluginLifecycleManager: Orchestrates discovery through shutdown
- Discovery: Entry points, config, and filesystem discovery

Example:
    ```python
    from soothe.plugin import PluginRegistry, PluginLifecycleManager
    from soothe.config.settings import SootheConfig

    # Create registry
    registry = PluginRegistry()

    # Load plugins
    lifecycle = PluginLifecycleManager(registry)
    await lifecycle.load_all(config)

    # Get tools and subagents
    tools = registry.get_all_tools()
    subagents = registry.get_all_subagents()
    ```
"""

from soothe.plugin.context import create_plugin_context
from soothe.plugin.discovery import (
    discover_all_plugins,
    discover_config_declared,
    discover_entry_points,
    discover_filesystem,
)
from soothe.plugin.events import (
    PluginFailedEvent,
    PluginLoadedEvent,
    PluginUnloadedEvent,
)
from soothe.plugin.exceptions import (
    DependencyError,
    DiscoveryError,
    InitializationError,
    PluginError,
    SubagentCreationError,
    ToolCreationError,
    ValidationError,
)
from soothe.plugin.lifecycle import PluginLifecycleManager
from soothe.plugin.loader import PluginLoader
from soothe.plugin.registry import PluginRegistry, RegistryEntry

__all__ = [
    # Exceptions
    "DependencyError",
    "DiscoveryError",
    "InitializationError",
    "PluginError",
    # Events
    "PluginFailedEvent",
    # Core classes
    "PluginLifecycleManager",
    "PluginLoadedEvent",
    "PluginLoader",
    "PluginRegistry",
    "PluginUnloadedEvent",
    "RegistryEntry",
    "SubagentCreationError",
    "ToolCreationError",
    "ValidationError",
    # Context
    "create_plugin_context",
    # Discovery
    "discover_all_plugins",
    "discover_config_declared",
    "discover_entry_points",
    "discover_filesystem",
]
