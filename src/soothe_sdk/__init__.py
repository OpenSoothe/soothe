"""Soothe SDK - Decorator-based API for building Soothe plugins.

This SDK provides a simple, decorator-based API for creating tools and subagents
that extend Soothe's capabilities. Plugin developers only need this lightweight
SDK package, not the full Soothe runtime.

Example:
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
"""

from soothe_sdk.decorators.plugin import plugin
from soothe_sdk.decorators.subagent import subagent
from soothe_sdk.decorators.tool import tool, tool_group
from soothe_sdk.exceptions import (
    DependencyError,
    DiscoveryError,
    InitializationError,
    PluginError,
    SubagentCreationError,
    ToolCreationError,
    ValidationError,
)
from soothe_sdk.types.context import PluginContext, SootheConfigProtocol
from soothe_sdk.types.health import PluginHealth
from soothe_sdk.types.manifest import PluginManifest

__version__ = "0.1.0"
__soothe_required_version__ = ">=0.1.0,<1.0.0"

__all__ = [
    # Decorators
    "plugin",
    "tool",
    "tool_group",
    "subagent",
    # Types
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
]
