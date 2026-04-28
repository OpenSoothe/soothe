"""Shared tool logging wrapper for subagents.

Provides a reusable wrapper that emits progress events when tools are invoked.
"""

from __future__ import annotations

import functools
import logging
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from soothe.utils.text_preview import preview_first

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from langchain_core.tools import BaseTool

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

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

    from soothe.core.events import (
        make_subagent_tool_completed,
        make_subagent_tool_failed,
        make_subagent_tool_started,
    )
    from soothe.utils.progress import emit_progress

    tool_name = tool.name if isinstance(tool, BaseTool) else getattr(tool, "__name__", "unknown")

    if isinstance(tool, BaseTool):
        # For BaseTool instances, wrap the underlying function while preserving the tool type
        # This is especially important for StructuredTool or tools that expect ToolRuntime
        if hasattr(tool, "func") and tool.func is not None:
            original_func = tool.func

            @functools.wraps(original_func)
            def logged_func(*args: Any, **kwargs: Any) -> Any:
                emit_progress(
                    make_subagent_tool_started(
                        subagent_name,
                        tool=tool_name,
                        args=preview_first(str(args), 200) if args else "",
                        kwargs=preview_first(str(kwargs), 200) if kwargs else "",
                    ),
                    logger,
                )
                try:
                    result = original_func(*args, **kwargs)
                except Exception as e:
                    emit_progress(
                        make_subagent_tool_failed(
                            subagent_name,
                            tool=tool_name,
                            error=preview_first(str(e), 200),
                        ),
                        logger,
                    )
                    raise
                else:
                    emit_progress(
                        make_subagent_tool_completed(
                            subagent_name,
                            tool=tool_name,
                            result_preview=preview_first(str(result), 300) if result else "",
                        ),
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
            make_subagent_tool_started(
                subagent_name,
                tool=tool_name,
                args=preview_first(str(args), 200) if args else "",
                kwargs=preview_first(str(kwargs), 200) if kwargs else "",
            ),
            logger,
        )
        try:
            result = tool(*args, **kwargs)
        except Exception as e:
            emit_progress(
                make_subagent_tool_failed(
                    subagent_name,
                    tool=tool_name,
                    error=preview_first(str(e), 200),
                ),
                logger,
            )
            raise
        else:
            emit_progress(
                make_subagent_tool_completed(
                    subagent_name,
                    tool=tool_name,
                    result_preview=preview_first(str(result), 300) if result else "",
                ),
                logger,
            )
            return result

    return logged_callable


# ---------------------------------------------------------------------------
# Thread-safe event emission for parallel tool execution
# ---------------------------------------------------------------------------

# Global lock for thread-safe event emission
_event_lock = threading.Lock()


@contextmanager
def thread_safe_event_emission() -> Generator[None, None, None]:
    """Ensure events from parallel tools don't interleave.

    Use this context manager when emitting events from concurrently executing
    tools to prevent interleaved output.

    Yields:
        None

    Example:
        ```python
        with thread_safe_event_emission():
            emit_tool_started(name, args)
            # ... execute tool ...
            emit_tool_completed(name, result)
        ```
    """
    with _event_lock:
        yield


def get_event_lock() -> threading.Lock:
    """Get the global event emission lock.

    Returns:
        The global threading.Lock instance for event emission.
    """
    return _event_lock
