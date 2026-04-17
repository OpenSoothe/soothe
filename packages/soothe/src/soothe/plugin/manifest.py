"""Re-export PluginManifest from SDK.

This module provides a local import path matching the RFC-600
specification: src/soothe/plugin/manifest.py

The actual implementation lives in soothe_sdk.types.manifest
to keep the SDK self-contained for third-party distribution.
"""

from soothe_sdk.plugin import Manifest as PluginManifest

__all__ = ["PluginManifest"]
