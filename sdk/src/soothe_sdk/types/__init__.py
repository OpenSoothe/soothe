"""Type definitions for the Soothe SDK."""

from soothe_sdk.types.context import PluginContext, SootheConfigProtocol
from soothe_sdk.types.health import PluginHealth
from soothe_sdk.types.manifest import PluginManifest

__all__ = [
    "PluginManifest",
    "PluginContext",
    "SootheConfigProtocol",
    "PluginHealth",
]
