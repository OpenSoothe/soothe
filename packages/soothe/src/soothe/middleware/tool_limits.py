"""Tool call limit and retry middleware for langchain agents."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain.agents.middleware.types import AgentMiddleware

    from soothe.config.models import InfrastructureLimitsConfig


def build_tool_limit_middleware(
    config: InfrastructureLimitsConfig,
) -> list[AgentMiddleware[Any, Any]]:
    """Build tool call limit middleware from config.

    Creates a global middleware and per-tool middlewares for tools with specific limits.

    Args:
        config: InfrastructureLimitsConfig with tool_call_limit settings.

    Returns:
        List of ToolCallLimitMiddleware instances.
    """
    from langchain.agents.middleware.tool_call_limit import ToolCallLimitMiddleware

    limits = config.tool_call_limit
    middlewares: list[AgentMiddleware[Any, Any]] = []

    # Global middleware
    global_mw = ToolCallLimitMiddleware(
        thread_limit=limits.global_thread_limit,
        run_limit=limits.global_run_limit,
        exit_behavior="continue",
    )
    middlewares.append(global_mw)

    # Tool-specific middlewares
    for tool_name, tool_limits in limits.tool_specific_limits.items():
        thread_lim = tool_limits.get("thread_limit")
        run_lim = tool_limits.get("run_limit")
        tool_mw = ToolCallLimitMiddleware(
            tool_name=tool_name,
            thread_limit=thread_lim,
            run_limit=run_lim,
            exit_behavior="continue",
        )
        middlewares.append(tool_mw)

    return middlewares


def build_tool_retry_middleware(
    config: InfrastructureLimitsConfig,
) -> list[AgentMiddleware[Any, Any]]:
    """Build tool retry middleware from config.

    Args:
        config: InfrastructureLimitsConfig with tool_retry settings.

    Returns:
        List containing a single ToolRetryMiddleware instance.
    """
    from langchain.agents.middleware.tool_retry import ToolRetryMiddleware

    retry = config.tool_retry
    middleware = ToolRetryMiddleware(
        max_retries=retry.max_retries,
        backoff_factor=retry.backoff_factor,
        initial_delay=retry.initial_delay,
        on_failure="continue",
    )
    return [middleware]
