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
    from soothe_sdk.ux.output_events import is_output_event
    from soothe_sdk.tools.metadata import get_tool_meta
    from soothe_sdk.utils.formatting import format_cli_error
    from soothe_sdk.plugin import plugin, tool
"""

__version__ = "0.4.0"
__soothe_required_version__ = ">=0.4.0,<1.0.0"

# Minimal exports - version + plugin decorators only
__all__ = [
    "__version__",
    "__soothe_required_version__",
    # Plugin decorators (convenience re-exports)
    "plugin",
    "subagent",
    "tool",
    "tool_group",
]

# Re-export plugin decorators for convenience (langchain-core pattern)
# Allows: from soothe_sdk import plugin (as well as from soothe_sdk.plugin import plugin)
from soothe_sdk.plugin import plugin, subagent, tool, tool_group  # noqa: F401
