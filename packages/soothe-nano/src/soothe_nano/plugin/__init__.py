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
    from soothe_nano.plugin import PluginRegistry, PluginLifecycleManager
    from soothe_nano.config.settings import SootheConfig

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

from soothe_nano.plugin.context import create_plugin_context
from soothe_nano.plugin.discovery import (
    discover_all_plugins,
    discover_config_declared,
    discover_entry_points,
    discover_filesystem,
)
from soothe_nano.plugin.events import (
    PluginFailedEvent,
    PluginHealthCheckedEvent,
    PluginLoadedEvent,
    PluginUnloadedEvent,
)
from soothe_nano.plugin.exceptions import (
    DependencyError,
    DiscoveryError,
    InitializationError,
    PluginError,
    SubagentCreationError,
    ToolCreationError,
    ValidationError,
)
from soothe_nano.plugin.lifecycle import PluginLifecycleManager
from soothe_nano.plugin.loader import PluginLoader
from soothe_nano.plugin.manifest import PluginManifest
from soothe_nano.plugin.registry import PluginRegistry, RegistryEntry

__all__ = [
    # Exceptions
    "DependencyError",
    "DiscoveryError",
    "InitializationError",
    "PluginError",
    # Events
    "PluginFailedEvent",
    "PluginHealthCheckedEvent",
    # Core classes
    "PluginLifecycleManager",
    "PluginLoadedEvent",
    "PluginLoader",
    "PluginManifest",
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
