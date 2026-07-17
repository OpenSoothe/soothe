"""Plugin development API for Soothe.

This package provides the complete plugin API including decorators,
types, and utilities for plugin authors.
"""

from soothe_sdk.plugin.context import PluginContext, SootheConfigProtocol
from soothe_sdk.plugin.decorators import plugin, subagent, tool, tool_group
from soothe_sdk.plugin.depends import library
from soothe_sdk.plugin.emit import emit_progress, set_stream_writer
from soothe_sdk.plugin.health import PluginHealth
from soothe_sdk.plugin.manifest import PluginManifest
from soothe_sdk.plugin.registry import register_event

__all__ = [
    "plugin",
    "tool",
    "tool_group",
    "subagent",
    "PluginManifest",
    "PluginContext",
    "SootheConfigProtocol",
    "PluginHealth",
    "library",
    "register_event",
    "emit_progress",
    "set_stream_writer",
]
