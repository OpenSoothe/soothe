"""Soothe Community Plugins.

This package contains community-contributed plugins for Soothe,
including subagents, tools, and other extensions built on the
RFC-0018 plugin system.

All plugins in this package are third-party contributions and follow
the standard plugin architecture with @plugin and @subagent decorators.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("soothe-plugins")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "__version__",
]
