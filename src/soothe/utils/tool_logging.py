"""Shared tool logging wrapper for subagents.

Provides a reusable wrapper that emits progress events when tools are invoked.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.tools import BaseTool


def wrap_tool_with_logging(
    tool: BaseTool | Callable[..., Any],
    subagent_name: str,
    logger: logging.Logger,
) -> BaseTool | Callable[..., Any]:
    """Wrap a tool to emit progress events on invocation.

    Args:
        tool: The tool to wrap (BaseTool or callable).
        subagent_name: Name of the subagent (for event type prefix).
        logger: Logger instance for the subagent.

    Returns:
        Wrapped tool that logs invocation and results.
    """
    from langchain_core.tools import BaseTool

    from soothe.utils.progress import emit_progress

    tool_name = tool.name if isinstance(tool, BaseTool) else getattr(tool, "__name__", "unknown")

    if isinstance(tool, BaseTool):
        # For BaseTool instances, wrap the underlying function while preserving the tool type
        # This is especially important for StructuredTool or tools that expect ToolRuntime
        if hasattr(tool, "func") and tool.func is not None:
            original_func = tool.func

            def logged_func(*args: Any, **kwargs: Any) -> Any:
                emit_progress(
                    {
                        "type": f"soothe.{subagent_name}.tool_start",
                        "tool": tool_name,
                        "args": str(args)[:200] if args else "",
                        "kwargs": str(kwargs)[:200] if kwargs else "",
                    },
                    logger,
                )
                try:
                    result = original_func(*args, **kwargs)
                except Exception as e:
                    emit_progress(
                        {
                            "type": f"soothe.{subagent_name}.tool_error",
                            "tool": tool_name,
                            "error": str(e)[:200],
                        },
                        logger,
                    )
                    raise
                else:
                    emit_progress(
                        {
                            "type": f"soothe.{subagent_name}.tool_end",
                            "tool": tool_name,
                            "result_preview": str(result)[:300] if result else "",
                        },
                        logger,
                    )
                    return result

            # Monkey-patch the tool's func instead of creating a new Tool instance
            # This preserves the original tool type (StructuredTool, etc.)
            tool.func = logged_func
            return tool
        # Tool has no func attribute (implements _run directly), return as-is
        logger.debug("Tool %s has no 'func' attribute, skipping logging wrapper", tool_name)
        return tool

    # For callable tools, wrap them directly
    def logged_callable(*args: Any, **kwargs: Any) -> Any:
        emit_progress(
            {
                "type": f"soothe.{subagent_name}.tool_start",
                "tool": tool_name,
                "args": str(args)[:200] if args else "",
                "kwargs": str(kwargs)[:200] if kwargs else "",
            },
            logger,
        )
        try:
            result = tool(*args, **kwargs)
        except Exception as e:
            emit_progress(
                {
                    "type": f"soothe.{subagent_name}.tool_error",
                    "tool": tool_name,
                    "error": str(e)[:200],
                },
                logger,
            )
            raise
        else:
            emit_progress(
                {
                    "type": f"soothe.{subagent_name}.tool_end",
                    "tool": tool_name,
                    "result_preview": str(result)[:300] if result else "",
                },
                logger,
            )
            return result

    return logged_callable


def wrap_main_agent_tool_with_logging(
    tool: BaseTool | Callable[..., Any],
    logger: logging.Logger,
) -> BaseTool | Callable[..., Any]:
    """Wrap a main agent tool to emit progress events on invocation.

    Uses event pattern: soothe.tool.{tool_name}.{started|completed|failed}

    Args:
        tool: The tool to wrap (BaseTool or callable).
        logger: Logger instance for the main agent.

    Returns:
        Wrapped tool that logs invocation and results.
    """
    from langchain_core.tools import BaseTool

    from soothe.utils.progress import emit_progress

    # Check if already wrapped to prevent double-wrapping
    if hasattr(tool, "_soothe_progress_wrapped") and tool._soothe_progress_wrapped:
        return tool

    tool_name = tool.name if isinstance(tool, BaseTool) else getattr(tool, "__name__", "unknown")

    if isinstance(tool, BaseTool):
        # For BaseTool instances, wrap the underlying function while preserving the tool type
        if hasattr(tool, "func") and tool.func is not None:
            original_func = tool.func

            def logged_func(*args: Any, **kwargs: Any) -> Any:
                emit_progress(
                    {
                        "type": f"soothe.tool.{tool_name}.started",
                        "tool": tool_name,
                        "args": str(args)[:200] if args else "",
                        "kwargs": str(kwargs)[:200] if kwargs else "",
                    },
                    logger,
                )
                try:
                    result = original_func(*args, **kwargs)
                except Exception as e:
                    emit_progress(
                        {
                            "type": f"soothe.tool.{tool_name}.failed",
                            "tool": tool_name,
                            "error": str(e)[:200],
                        },
                        logger,
                    )
                    raise
                else:
                    emit_progress(
                        {
                            "type": f"soothe.tool.{tool_name}.completed",
                            "tool": tool_name,
                            "result_preview": str(result)[:300] if result else "",
                        },
                        logger,
                    )
                    return result

            # Monkey-patch the tool's func and mark as wrapped
            tool.func = logged_func
            tool._soothe_progress_wrapped = True
            return tool
        # Tool has no func attribute (implements _run directly), return as-is
        logger.debug("Tool %s has no 'func' attribute, skipping logging wrapper", tool_name)
        return tool

    # For callable tools, wrap them directly
    def logged_callable(*args: Any, **kwargs: Any) -> Any:
        emit_progress(
            {
                "type": f"soothe.tool.{tool_name}.started",
                "tool": tool_name,
                "args": str(args)[:200] if args else "",
                "kwargs": str(kwargs)[:200] if kwargs else "",
            },
            logger,
        )
        try:
            result = tool(*args, **kwargs)
        except Exception as e:
            emit_progress(
                {
                    "type": f"soothe.tool.{tool_name}.failed",
                    "tool": tool_name,
                    "error": str(e)[:200],
                },
                logger,
            )
            raise
        else:
            emit_progress(
                {
                    "type": f"soothe.tool.{tool_name}.completed",
                    "tool": tool_name,
                    "result_preview": str(result)[:300] if result else "",
                },
                logger,
            )
            return result

    # Mark as wrapped
    logged_callable._soothe_progress_wrapped = True
    return logged_callable
