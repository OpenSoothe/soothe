"""Soothe SDK - Minimal __init__.py matching langchain-core pattern.

This SDK provides decorator-based API for building Soothe plugins
and client utilities for WebSocket communication with the daemon.

Following langchain-core pattern: minimal __init__.py (version only).
Use package-level imports instead of root-level re-exports.

Example imports:
    from soothe_sdk.plugin import plugin, tool, Manifest
    from soothe_sdk.client import WebSocketClient
    from soothe_sdk.events import SootheEvent
    from soothe_sdk.exceptions import PluginError
    from soothe_sdk.verbosity import VerbosityTier
    from soothe_sdk.protocols import PersistStore
    from soothe_sdk.utils import setup_logging
"""

__version__ = "0.4.0"
__soothe_required_version__ = ">=0.4.0,<1.0.0"

# No re-exports - use package imports for clarity and performance
# Core concepts remain accessible at root level:
# - soothe_sdk.events (SootheEvent, LifecycleEvent, etc.)
# - soothe_sdk.exceptions (PluginError, ValidationError, etc.)
# - soothe_sdk.verbosity (VerbosityTier, should_show)
# - soothe_sdk.protocols (PersistStore, PolicyProtocol, etc.)
