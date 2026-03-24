"""Plugin lifecycle events.

This module defines event types emitted during the plugin lifecycle.
All events follow the soothe.* event namespace pattern.
"""

from typing import Literal

from pydantic import BaseModel


class PluginLoadedEvent(BaseModel):
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


class PluginFailedEvent(BaseModel):
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


class PluginUnloadedEvent(BaseModel):
    """Emitted when a plugin is unloaded.

    This event signals that a plugin's on_unload() hook has been called
    and the plugin is no longer available.

    Attributes:
        type: Event type identifier ("soothe.plugin.unloaded").
        name: Plugin name.
    """

    type: Literal["soothe.plugin.unloaded"] = "soothe.plugin.unloaded"
    name: str


class PluginHealthCheckedEvent(BaseModel):
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
