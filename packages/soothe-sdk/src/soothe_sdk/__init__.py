"""Soothe SDK - Decorator-based API for building Soothe plugins and client utilities.

This SDK provides:
1. A simple, decorator-based API for creating tools and subagents
2. Client-side utilities for WebSocket communication with daemon
3. Shared types, protocols, and helpers for both CLI and daemon

Plugin developers only need this lightweight SDK package, not the full Soothe runtime.

Example plugin:
    ```python
    from soothe_sdk import plugin, tool, subagent


    @plugin(
        name="my-plugin",
        version="1.0.0",
        description="My awesome plugin",
        dependencies=["langchain>=0.1.0"],
    )
    class MyPlugin:
        @tool(name="greet", description="Greet someone")
        def greet(self, name: str) -> str:
            return f"Hello, {name}!"

        @subagent(name="researcher", description="Research subagent")
        async def create_researcher(self, model, config, context):
            # ... create subagent ...
            pass
    ```

Example client:
    ```python
    from soothe_sdk.client import WebSocketClient, bootstrap_thread_session

    client = WebSocketClient(url="ws://localhost:8765")
    await client.connect()
    status = await bootstrap_thread_session(client, resume_thread_id=None, verbosity="normal")
    await client.send_input("Research AI advances")
    ```
"""

# Client utilities (v0.2.0)
from soothe_sdk.client import (
    VerbosityLevel,
    WebSocketClient,
    bootstrap_thread_session,
    connect_websocket_with_retries,
)

# Phase 1 exports (IG-174: CLI import violations fix)
from soothe_sdk.config_constants import DEFAULT_EXECUTE_TIMEOUT, SOOTHE_HOME
from soothe_sdk.decorators.plugin import plugin
from soothe_sdk.decorators.subagent import subagent
from soothe_sdk.decorators.tool import tool, tool_group
from soothe_sdk.events import (
    ErrorEvent,
    LifecycleEvent,
    OutputEvent,
    ProtocolEvent,
    SootheEvent,
    SubagentEvent,
)
from soothe_sdk.exceptions import (
    DependencyError,
    DiscoveryError,
    InitializationError,
    PluginError,
    SubagentCreationError,
    ToolCreationError,
    ValidationError,
)
from soothe_sdk.internal import INTERNAL_JSON_KEYS, strip_internal_tags
from soothe_sdk.logging_utils import GlobalInputHistory, setup_logging
from soothe_sdk.protocol import decode, encode
from soothe_sdk.protocol_schemas import Plan, PlanStep, ToolOutput
from soothe_sdk.types.context import PluginContext, SootheConfigProtocol
from soothe_sdk.types.health import PluginHealth
from soothe_sdk.types.manifest import PluginManifest
from soothe_sdk.utils import (
    _TASK_NAME_RE,
    convert_and_abbreviate_path,
    format_cli_error,
    get_tool_display_name,
    log_preview,
    parse_autopilot_goals,
)
from soothe_sdk.ux_types import ESSENTIAL_EVENT_TYPES
from soothe_sdk.verbosity import (
    ProgressCategory,
    VerbosityTier,
    classify_event_to_tier,
    should_show,
)
from soothe_sdk.workspace_types import INVALID_WORKSPACE_DIRS

__version__ = "0.3.0"
__soothe_required_version__ = ">=0.2.0,<1.0.0"

__all__ = [
    # Decorators
    "plugin",
    "tool",
    "tool_group",
    "subagent",
    # Plugin types
    "PluginManifest",
    "PluginContext",
    "SootheConfigProtocol",
    "PluginHealth",
    # Exceptions
    "PluginError",
    "DiscoveryError",
    "ValidationError",
    "DependencyError",
    "InitializationError",
    "ToolCreationError",
    "SubagentCreationError",
    # Client utilities (v0.2.0)
    "WebSocketClient",
    "VerbosityLevel",
    "bootstrap_thread_session",
    "connect_websocket_with_retries",
    # Protocol
    "encode",
    "decode",
    # Events
    "SootheEvent",
    "LifecycleEvent",
    "ProtocolEvent",
    "SubagentEvent",
    "OutputEvent",
    "ErrorEvent",
    # Verbosity
    "VerbosityTier",
    "should_show",
    "classify_event_to_tier",
    "ProgressCategory",
    # Internal
    "INTERNAL_JSON_KEYS",
    "strip_internal_tags",
    # Types
    "INVALID_WORKSPACE_DIRS",
    # UX types
    "ESSENTIAL_EVENT_TYPES",
    # Phase 1 exports (IG-174)
    "SOOTHE_HOME",
    "DEFAULT_EXECUTE_TIMEOUT",
    "Plan",
    "PlanStep",
    "ToolOutput",
    "GlobalInputHistory",
    "setup_logging",
    "format_cli_error",
    "log_preview",
    "convert_and_abbreviate_path",
    "parse_autopilot_goals",
    "get_tool_display_name",
    "_TASK_NAME_RE",
]
