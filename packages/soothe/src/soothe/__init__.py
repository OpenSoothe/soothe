"""Soothe - Goal-driven multi-agent orchestration framework."""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("soothe")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = []
