"""Soothe SDK — slim contracts for plugins, wire, display, and protocols.

Root package exports version metadata only (langchain-core style).
Import from subpackages:

    from soothe_sdk.plugin import plugin, tool, subagent
    from soothe_sdk.core.events import SootheEvent
    from soothe_sdk.wire.codec import messages_from_wire_dicts
    from soothe_sdk.paths import SOOTHE_HOME
    from soothe_sdk.protocols import AsyncPersistStore
"""

import importlib
import importlib.metadata

# Load before plugin stack so LangGraph serde import-time Reviver() warning is filtered.
importlib.import_module("soothe_sdk._upstream_warnings")

try:
    __version__ = importlib.metadata.version("soothe-sdk")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

__soothe_required_version__ = ">=0.5.0,<1.0.0"

__all__ = [
    "__version__",
    "__soothe_required_version__",
]
