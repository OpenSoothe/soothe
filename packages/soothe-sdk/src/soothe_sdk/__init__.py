"""Soothe SDK - Minimal __init__.py matching langchain-core pattern.

This SDK provides decorator-based API for building Soothe plugins
and client utilities for WebSocket communication with the daemon.

Following langchain-core pattern: minimal __init__.py (version only).
Use package-level imports instead of root-level re-exports.

Canonical import paths (IG-259 refactoring):
    from soothe_sdk.core.events import SootheEvent
    from soothe_sdk.core.types import VerbosityLevel
    from soothe_sdk.core.verbosity import VerbosityTier
    from soothe_sdk.core.exceptions import PluginError
    from soothe_sdk.client.wire import messages_from_wire_dicts
    from soothe_sdk.ux.loop_stream import assistant_output_phase
    from soothe_sdk.tools.metadata import get_tool_meta
    from soothe_sdk.utils.formatting import format_cli_error
    from soothe_sdk.plugin import plugin, tool
"""

import importlib
import importlib.metadata

# Load before plugin stack so LangGraph serde import-time Reviver() warning is filtered.
importlib.import_module("soothe_sdk._upstream_warnings")

from soothe_sdk.client.config import SOOTHE_HOME  # noqa: E402, F401
from soothe_sdk.core.events import SubagentEvent  # noqa: E402, F401
from soothe_sdk.core.exceptions import PluginError  # noqa: E402, F401
from soothe_sdk.core.verbosity import VerbosityTier  # noqa: E402, F401
from soothe_sdk.plugin import plugin, subagent, tool, tool_group  # noqa: E402, F401
from soothe_sdk.plugin.emit import emit_progress  # noqa: E402, F401
from soothe_sdk.plugin.registry import register_event  # noqa: E402, F401
from soothe_sdk.protocols import (  # noqa: E402, F401
    ActionRequest,
    PermissionSet,
    PersistStore,
    PolicyContext,
    VectorStoreProtocol,
)

try:
    __version__ = importlib.metadata.version("soothe-sdk")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

__soothe_required_version__ = ">=0.5.0,<1.0.0"

__all__ = [
    "__version__",
    "__soothe_required_version__",
    # Core
    "PluginError",
    "SubagentEvent",
    "VerbosityTier",
    # Plugin API
    "plugin",
    "subagent",
    "tool",
    "tool_group",
    "register_event",
    "emit_progress",
    # Protocols (legacy root imports)
    "PersistStore",
    "VectorStoreProtocol",
    "ActionRequest",
    "PermissionSet",
    "PolicyContext",
    # Client config
    "SOOTHE_HOME",
]
