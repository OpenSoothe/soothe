"""Plugin development API for Soothe.

This package provides the complete plugin API including decorators,
types, and utilities for plugin authors.
"""

from soothe_sdk.plugin.context import PluginContext as Context
from soothe_sdk.plugin.context import SootheConfigProtocol
from soothe_sdk.plugin.decorators import plugin, subagent, tool, tool_group
from soothe_sdk.plugin.depends import library as Depends  # noqa: N812
from soothe_sdk.plugin.emit import emit_progress, set_stream_writer
from soothe_sdk.plugin.health import PluginHealth as Health
from soothe_sdk.plugin.manifest import PluginManifest as Manifest
from soothe_sdk.plugin.registry import register_event

__all__ = [
    "plugin",
    "tool",
    "tool_group",
    "subagent",
    "Manifest",
    "Context",
    "SootheConfigProtocol",
    "Health",
    "Depends",
    "register_event",
    "emit_progress",
    "set_stream_writer",
]
