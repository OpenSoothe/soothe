"""@tool and @tool_group decorators for defining Soothe tools.

These decorators mark methods as langchain-compatible tools that can be
used by Soothe agents.
"""

from collections.abc import Callable
from functools import wraps
from typing import Any


def tool(
    name: str,
    description: str = "",
    group: str | None = None,
    display_name: str | None = None,
) -> Callable:
    """Decorator that marks a method as a langchain tool.

    This decorator attaches metadata to a method that identifies it as a tool
    for use by Soothe agents. The tool will be converted to a langchain BaseTool
    by the plugin loader.

    Args:
        name: Tool name (used to invoke the tool).
        description: Tool description for the LLM (shown in tool selection).
        group: Optional tool group name for organization.
        display_name: Optional user-facing display name (PascalCase). If not provided,
            will be auto-converted from name (snake_case -> PascalCase).

    Returns:
        Decorated method with tool metadata.

    Example:
        ```python
        @plugin(name="my-plugin", version="1.0.0", description="My plugin")
        class MyPlugin:
            @tool(name="greet", description="Greet someone by name", display_name="Greet")
            def greet(self, name: str) -> str:
                return f"Hello, {name}!"
        ```
    """

    def decorator(func: Callable) -> Callable:
        # Compute display name if not provided
        computed_display_name = display_name or name.replace("_", " ").title().replace(" ", "")

        # Mark as tool
        func._is_tool = True
        func._tool_name = name
        func._tool_description = description
        func._tool_group = group
        func._tool_display_name = computed_display_name

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
        wrapper._tool_display_name = computed_display_name

        # Register display name if explicitly provided
        if display_name:
            from soothe.tools.display_names import register_tool_display_name

            register_tool_display_name(name, display_name)

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
