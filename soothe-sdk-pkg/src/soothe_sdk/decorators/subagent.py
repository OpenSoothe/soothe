"""@subagent decorator for defining Soothe subagents.

This decorator marks a method as a subagent factory that creates
deepagents-compatible subagent instances.
"""

from collections.abc import Callable
from functools import wraps


def subagent(
    name: str,
    description: str,
    model: str | None = None,
    display_name: str | None = None,
) -> Callable:
    """Decorator that marks a method as a subagent factory.

    This decorator attaches metadata to a method that identifies it as a
    subagent factory. The method should create and return a subagent
    compatible with deepagents (SubAgent or CompiledSubAgent).

    Args:
        name: Subagent name (used in task tool to invoke subagent).
        description: Subagent description for the task tool.
        model: Optional default model string (e.g., "openai:gpt-4o-mini").
        display_name: Optional user-facing display name. If not provided,
            auto-converts from snake_case to PascalCase.

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
        # Determine display name
        final_display_name = display_name or name.replace("_", " ").title().replace(" ", "")

        # Register display name if custom name provided
        if display_name:
            # Lazy import to avoid circular dependency
            from soothe.tools.display_names import register_tool_display_name

            register_tool_display_name(name, final_display_name)

        # Mark as subagent factory
        func._is_subagent = True
        func._subagent_name = name
        func._subagent_description = description
        func._subagent_model = model
        func._subagent_display_name = final_display_name

        @wraps(func)
        async def wrapper(self, model, config, context, **kwargs):
            """Wrapper for subagent factory execution."""
            return await func(self, model, config, context, **kwargs)

        # Copy metadata to wrapper
        wrapper._is_subagent = True
        wrapper._subagent_name = name
        wrapper._subagent_description = description
        wrapper._subagent_model = model
        wrapper._subagent_display_name = final_display_name

        return wrapper

    return decorator
