"""Plugin lifecycle events.

This module defines event types emitted during the plugin lifecycle.
All events follow the soothe.* event namespace pattern.

Events are self-registered at module load time using register_event().
"""

from typing import Literal

from soothe.core.base_events import SootheEvent


class PluginLoadedEvent(SootheEvent):
    """Emitted when a plugin is successfully loaded.

    This event signals that a plugin has completed its initialization
    and is ready to provide tools and/or subagents.

    Attributes:
        type: Event type identifier ("soothe.plugin.loaded").
        name: Plugin name.
        version: Plugin version.
        source: Discovery source (built-in, entry_point, config, filesystem).
    """

    type: Literal["soothe.plugin.loaded"] = "soothe.plugin.loaded"
    name: str
    version: str
    source: str


class PluginFailedEvent(SootheEvent):
    """Emitted when a plugin fails to load.

    This event signals that a plugin failed during one of the loading phases.
    The plugin will not be available for use.

    Attributes:
        type: Event type identifier ("soothe.plugin.failed").
        name: Plugin name (may be empty if failure occurred before manifest parsing).
        error: Error message describing the failure.
        phase: Loading phase where the failure occurred (discovery, validation, dependency, initialization).
    """

    type: Literal["soothe.plugin.failed"] = "soothe.plugin.failed"
    name: str = ""
    error: str
    phase: Literal["discovery", "validation", "dependency", "initialization"]


class PluginUnloadedEvent(SootheEvent):
    """Emitted when a plugin is unloaded.

    This event signals that a plugin's on_unload() hook has been called
    and the plugin is no longer available.

    Attributes:
        type: Event type identifier ("soothe.plugin.unloaded").
        name: Plugin name.
    """

    type: Literal["soothe.plugin.unloaded"] = "soothe.plugin.unloaded"
    name: str


class PluginHealthCheckedEvent(SootheEvent):
    """Emitted when a plugin health check completes.

    This event signals the result of a plugin's health_check() call.

    Attributes:
        type: Event type identifier ("soothe.plugin.health_checked").
        name: Plugin name.
        status: Health status (healthy, degraded, unhealthy).
        message: Optional message with additional details.
    """

    type: Literal["soothe.plugin.health_checked"] = "soothe.plugin.health_checked"
    name: str
    status: Literal["healthy", "degraded", "unhealthy"]
    message: str = ""


# Register all plugin events with the global registry
# This happens at module load time
from soothe.core.event_catalog import register_event  # noqa: E402
from soothe.core.verbosity_tier import VerbosityTier  # noqa: E402

register_event(
    PluginLoadedEvent,
    summary_template="Plugin {name} v{version} loaded from {source}",
)
register_event(
    PluginFailedEvent,
    verbosity=VerbosityTier.QUIET,
    summary_template="Plugin {name} failed during {phase}: {error}",
)
register_event(
    PluginUnloadedEvent,
    summary_template="Plugin {name} unloaded",
)
register_event(
    PluginHealthCheckedEvent,
    summary_template="Plugin {name} health: {status}",
)

__all__ = [
    "PluginFailedEvent",
    "PluginHealthCheckedEvent",
    "PluginLoadedEvent",
    "PluginUnloadedEvent",
]
