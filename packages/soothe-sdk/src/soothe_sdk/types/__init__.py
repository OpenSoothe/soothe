"""Types package - DEPRECATED.

All types have been moved to their respective packages:
- PluginManifest → soothe_sdk.plugin.Manifest
- PluginContext → soothe_sdk.plugin.Context
- SootheConfigProtocol → soothe_sdk.plugin.SootheConfigProtocol
- PluginHealth → soothe_sdk.plugin.Health

This package is empty and will be removed in future versions.

Migration (v0.3.x → v0.4.0):
    # Old:
    from soothe_sdk.types import PluginManifest

    # New:
    from soothe_sdk.plugin import Manifest
"""

# No exports - package deprecated
__all__ = []
