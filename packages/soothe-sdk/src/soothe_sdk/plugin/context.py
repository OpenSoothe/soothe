"""Plugin context and protocol definitions.

This module defines the PluginContext that provides plugins with access to
Soothe internals, and the SootheConfigProtocol that decouples the SDK from
the concrete SootheConfig implementation.
"""

import logging
from collections.abc import Callable
from typing import Any, Protocol


class SootheConfigProtocol(Protocol):
    """Protocol defining the interface SootheConfig must implement.

    This protocol enables the SDK to reference SootheConfig functionality
    without creating a circular dependency. The main Soothe package's
    SootheConfig class implements this protocol.

    Methods:
        resolve_model: Resolve a model role to a provider:model string.
        get_plugin_config: Get plugin-specific configuration dictionary.
    """

    def resolve_model(self, role: str) -> str:
        """Resolve a model role to a provider:model string.

        Args:
            role: Model role (e.g., "default", "planner", "fast").

        Returns:
            Model identifier string (e.g., "openai:gpt-4o-mini").
        """
        ...

    def get_plugin_config(self, name: str) -> dict[str, Any]:
        """Get plugin-specific configuration.

        Args:
            name: Plugin name.

        Returns:
            Configuration dictionary for the plugin.
        """
        ...


class PluginContext:
    """Context provided to plugin lifecycle hooks (IG-175: Expanded with services).

    This class provides plugins with access to Soothe configuration,
    logging, event emission, and runtime service injection.

    Attributes:
        config: Plugin-specific configuration dictionary.
        soothe_config: Soothe configuration (via protocol).
        logger: Python logger instance for this plugin.
        services: Runtime services dict (populated by daemon during plugin loading).
            Keys include: "policy", "persistence", "emit_progress", "vector_store".
    """

    def __init__(
        self,
        config: dict[str, Any],
        soothe_config: SootheConfigProtocol,
        logger: logging.Logger,
        emit_event: Callable[[str, dict[str, Any]], None],
        services: dict[str, Any] | None = None,
    ):
        """Initialize plugin context.

        Args:
            config: Plugin-specific configuration.
            soothe_config: Soothe configuration object.
            logger: Logger instance for this plugin.
            emit_event: Callback to emit events.
            services: Runtime services dict (optional, defaults to empty dict).
        """
        self.config = config
        self.soothe_config = soothe_config
        self.logger = logger
        self._emit_event = emit_event
        self.services: dict[str, Any] = services or {}

    def emit_event(self, name: str, data: dict[str, Any]) -> None:
        """Emit a plugin event.

        Args:
            name: Event name (e.g., "plugin.loaded").
            data: Event data dictionary.
        """
        self._emit_event(name, data)
