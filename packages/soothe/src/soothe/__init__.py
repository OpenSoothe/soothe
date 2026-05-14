"""Soothe - Goal-driven multi-agent orchestration framework."""

import importlib.metadata

from soothe_sdk import _upstream_warnings as _upstream_warnings  # noqa: F401

try:
    __version__ = importlib.metadata.version("soothe")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = []
