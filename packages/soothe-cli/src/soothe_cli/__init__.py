"""Soothe CLI client - communicates with daemon via WebSocket."""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("soothe-cli")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = []
