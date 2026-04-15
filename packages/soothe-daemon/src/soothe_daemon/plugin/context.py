"""Plugin context creation and management.

This module provides utilities for creating PluginContext instances
with Soothe-specific context fields and event emission integration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe_sdk.types.context import PluginContext

if TYPE_CHECKING:
    from soothe_daemon.config.settings import SootheConfig

logger = logging.getLogger(__name__)


def create_plugin_context(
    plugin_name: str,
    config: dict[str, Any],
    soothe_config: SootheConfig,
    emit_event_callback: Any | None = None,
    **extra_context: Any,
) -> PluginContext:
    """Create a PluginContext instance for a plugin.

    This factory function creates a PluginContext with proper initialization
    for Soothe's event system and optional extra context fields.

    Args:
        plugin_name: Name of the plugin (used for logger naming).
        config: Plugin-specific configuration dictionary.
        soothe_config: Soothe configuration instance.
        emit_event_callback: Optional callback for event emission.
            If None, events are logged but not emitted.
        **extra_context: Additional context fields to attach.
            Used for special cases like GoalEngine injection.

    Returns:
        Configured PluginContext instance.

    Example:
        ```python
        context = create_plugin_context(
            plugin_name="goals",
            config={"max_goals": 10},
            soothe_config=config,
            goal_engine=goal_engine,  # Special injection
        )
        ```
    """
    # Create plugin-specific logger
    plugin_logger = logging.getLogger(f"soothe.plugins.{plugin_name}")

    # Create event emission wrapper
    def emit_event_wrapper(name: str, data: dict[str, Any]) -> None:
        """Wrapper for event emission.

        If emit_event_callback is provided, calls it.
        Otherwise, logs the event as a debug message.
        """
        if emit_event_callback:
            emit_event_callback(name, data)
        else:
            logger.debug("Plugin event: %s -> %s", name, data)

    # Create context
    context = PluginContext(
        config=config,
        soothe_config=soothe_config,
        logger=plugin_logger,
        emit_event=emit_event_wrapper,
    )

    # Attach extra context fields
    for key, value in extra_context.items():
        setattr(context, key, value)

    return context
