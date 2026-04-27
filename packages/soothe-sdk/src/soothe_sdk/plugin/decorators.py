"""Plugin decorators for defining Soothe tools and subagents.

These decorators mark classes and methods as Soothe plugins, tools, and subagents
with metadata for the plugin loader.

Decorators:
- @plugin - Marks a class as a Soothe plugin
- @tool - Marks a method as a langchain tool
- @tool_group - Marks a class as a collection of related tools
- @subagent - Marks a method as a subagent factory
"""

from collections.abc import Callable
from functools import wraps
from typing import Any

from soothe_sdk.core.exceptions import PluginError
from soothe_sdk.plugin.manifest import PluginManifest as Manifest


def plugin(
    name: str | None = None,
    version: str | None = None,
    description: str | None = None,
    author: str = "",
    homepage: str = "",
    repository: str = "",
    license: str = "MIT",
    dependencies: list[str] | None = None,
    python_version: str = ">=3.11",
    soothe_version: str = ">=0.1.0",
    config_requirements: list[str] | None = None,
    trust_level: str = "standard",
) -> Callable[[type], type]:
    """Decorator that marks a class as a Soothe plugin.

    This decorator attaches a PluginManifest to the class and adds helper
    methods for extracting tools and subagents.

    Args:
        name: Unique plugin identifier (lowercase, hyphenated).
        version: Semantic version string (e.g., "1.0.0").
        description: Human-readable description.
        author: Author name or organization.
        homepage: Project homepage URL.
        repository: Source repository URL.
        license: License identifier (SPDX format).
        dependencies: List of library dependencies (PEP 440 format).
        python_version: Python version constraint (PEP 440).
        soothe_version: Soothe version constraint (PEP 440).
        trust_level: Trust level ("built-in", "trusted", "standard", "untrusted").

    Returns:
        Decorated class with manifest and helper methods.

    Example:
        ```python
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
        ```
    """

    def decorator(cls: type) -> type:
        if not name:
            raise PluginError("Plugin name is required")
        if not version:
            raise PluginError("Plugin version is required")
        if not description:
            raise PluginError("Plugin description is required")

        # Create and attach manifest
        cls._plugin_manifest = Manifest(
            name=name,
            version=version,
            description=description,
            author=author,
            homepage=homepage,
            repository=repository,
            license=license,
            dependencies=dependencies or [],
            python_version=python_version,
            soothe_version=soothe_version,
            config_requirements=config_requirements or [],
            trust_level=trust_level,
        )
        # Legacy metadata used by older tests and plugin scaffolds.
        cls._plugin_metadata = {
            "name": name,
            "version": version,
            "description": description,
            "author": author,
            "homepage": homepage,
            "repository": repository,
            "license": license,
        }

        # Add manifest property
        @property
        def manifest(self) -> Manifest:
            """Return the plugin manifest."""
            return self._plugin_manifest

        cls.manifest = manifest

        # Add get_tools() method to extract @tool decorated methods
        def get_tools(self) -> list[Any]:
            """Extract all tools from this plugin.

            Returns:
                List of tool functions with _is_tool metadata.
            """
            tools = []
            for attr_name in dir(self):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(self, attr_name)
                if callable(attr) and hasattr(attr, "_is_tool"):
                    tools.append(attr)
            return tools

        cls.get_tools = get_tools

        # Add get_subagents() method to extract @subagent decorated methods
        def get_subagents(self) -> list[Any]:
            """Extract all subagents from this plugin.

            Returns:
                List of subagent factory functions with _is_subagent metadata.
            """
            subagents = []
            for attr_name in dir(self):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(self, attr_name)
                if callable(attr) and hasattr(attr, "_is_subagent"):
                    subagents.append(attr)
            return subagents

        cls.get_subagents = get_subagents

        return cls

    return decorator


def tool(
    name: str,
    description: str = "",
    group: str | None = None,
    system_context: str | None = None,
    triggers: list[str] | None = None,
) -> Callable:
    """Decorator that marks a method as a langchain tool.

    This decorator attaches metadata to a method that identifies it as a tool
    for use by Soothe agents. The tool will be converted to a langchain BaseTool
    by the plugin loader.

    Display names are automatically generated from snake_case to PascalCase
    (e.g., "read_file" → "ReadFile").

    Args:
        name: Tool name in snake_case (used to invoke the tool).
        description: Tool description for the LLM (shown in tool selection).
        group: Optional tool group name for organization.
        system_context: Optional XML fragment for system message when tool is active (RFC-210).
        triggers: Optional list of system section names this tool triggers (RFC-210).

    Returns:
        Decorated method with tool metadata.

    Example:
        ```python
        @plugin(name="my-plugin", version="1.0.0", description="My plugin")
        class MyPlugin:
            @tool(name="greet", description="Greet someone by name")
            def greet(self, name: str) -> str:
                return f"Hello, {name}!"

            @tool(name="custom_op", description="Custom operation")
            def custom_operation(self, data: str) -> str:
                return f"Processed: {data}"
        ```
    """

    def decorator(func: Callable) -> Callable:
        # Mark as tool
        func._is_tool = True
        func._tool_name = name
        func._tool_description = description
        func._tool_group = group
        func._tool_system_context = system_context  # RFC-210
        func._tool_triggers = triggers or []  # RFC-210
        func._tool_metadata = {"name": name, "description": description}

        @wraps(func)
        async def async_wrapper(self, *args, **kwargs):
            """Async wrapper for tool execution."""
            return await func(self, *args, **kwargs)

        @wraps(func)
        def sync_wrapper(self, *args, **kwargs):
            """Sync wrapper for tool execution."""
            return func(self, *args, **kwargs)

        # Choose wrapper based on function type
        import asyncio

        if asyncio.iscoroutinefunction(func):
            wrapper = async_wrapper
        else:
            wrapper = sync_wrapper

        # Copy metadata to wrapper
        wrapper._is_tool = True
        wrapper._tool_name = name
        wrapper._tool_description = description
        wrapper._tool_group = group
        wrapper._tool_system_context = system_context  # RFC-210
        wrapper._tool_triggers = triggers or []  # RFC-210
        wrapper._tool_metadata = {"name": name, "description": description}

        return wrapper

    return decorator


def tool_group(
    name: str,
    description: str = "",
) -> Callable[[type], type]:
    """Decorator that marks a class as a collection of related tools.

    This decorator is used to organize multiple tools into a logical group.
    Tool groups provide better organization and can be enabled/disabled
    together.

    Args:
        name: Tool group name.
        description: Tool group description.

    Returns:
        Decorated class with tool group metadata.

    Example:
        ```python
        @plugin(name="research", version="1.0.0", description="Research tools")
        class ResearchPlugin:
            @tool_group(name="research", description="Academic research tools")
            class ResearchTools:
                @tool(name="arxiv")
                def search_arxiv(self, query: str) -> list:
                    pass

                @tool(name="scholar")
                def search_scholar(self, query: str) -> list:
                    pass
        ```
    """

    def decorator(cls: type) -> type:
        cls._is_tool_group = True
        cls._tool_group_name = name
        cls._tool_group_description = description

        # Add method to extract tools from group
        def get_tools(self) -> list[Any]:
            """Extract all tools from this tool group.

            Returns:
                List of tool methods with _is_tool metadata.
            """
            tools = []
            for attr_name in dir(self):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(self, attr_name)
                if callable(attr) and hasattr(attr, "_is_tool"):
                    tools.append(attr)
            return tools

        cls.get_tools = get_tools

        return cls

    return decorator


def subagent(
    name: str,
    description: str,
    model: str | None = None,
    system_context: str | None = None,
    triggers: list[str] | None = None,
) -> Callable:
    """Decorator that marks a method as a subagent factory.

    This decorator attaches metadata to a method that identifies it as a
    subagent factory. The method should create and return a subagent
    compatible with deepagents (SubAgent or CompiledSubAgent).

    Display names are automatically generated from snake_case to PascalCase
    (e.g., "my_agent" → "MyAgent").

    Args:
        name: Subagent name in snake_case (used in task tool to invoke subagent).
        description: Subagent description for the task tool.
        model: Optional default model string (e.g., "openai:gpt-4o-mini").
        system_context: Optional XML fragment for system message when subagent is active (RFC-210).
        triggers: Optional list of system section names this subagent triggers (RFC-210).

    Returns:
        Decorated method with subagent metadata.

    Example:
        ```python
        @plugin(name="research", version="1.0.0", description="Research plugin")
        class ResearchPlugin:
            @subagent(
                name="researcher",
                description="Research subagent with web search",
                model="openai:gpt-4o-mini",
            )
            async def create_researcher(self, model, config, context):
                from langgraph.prebuilt import create_react_agent

                # Create agent
                agent = create_react_agent(model, tools)

                return {
                    "name": "researcher",
                    "description": "Research subagent",
                    "runnable": agent,
                }
        ```

    Note:
        The factory method signature should be:
        `async def create_subagent(self, model, config, context, **kwargs)`

        Where:
        - model: Resolved BaseChatModel or model string
        - config: SootheConfig instance
        - context: PluginContext instance
        - **kwargs: Subagent-specific configuration from config.yml
    """

    def decorator(func: Callable) -> Callable:
        # Mark as subagent factory
        func._is_subagent = True
        func._subagent_name = name
        func._subagent_description = description
        func._subagent_model = model
        func._subagent_system_context = system_context  # RFC-210
        func._subagent_triggers = triggers or []  # RFC-210
        func._subagent_metadata = {"name": name, "description": description, "model": model}

        @wraps(func)
        async def wrapper(self, model, config, context, **kwargs):
            """Wrapper for subagent factory execution."""
            return await func(self, model, config, context, **kwargs)

        # Copy metadata to wrapper
        wrapper._is_subagent = True
        wrapper._subagent_name = name
        wrapper._subagent_description = description
        wrapper._subagent_model = model
        wrapper._subagent_system_context = system_context  # RFC-210
        wrapper._subagent_triggers = triggers or []  # RFC-210
        wrapper._subagent_metadata = {"name": name, "description": description, "model": model}

        return wrapper

    return decorator


__all__ = [
    "plugin",
    "tool",
    "tool_group",
    "subagent",
]
