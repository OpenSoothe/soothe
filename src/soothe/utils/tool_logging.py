"""Shared tool logging wrapper for subagents.

Provides a reusable wrapper that emits progress events when tools are invoked.
"""

from __future__ import annotations

import functools
import logging
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

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

    from soothe.core.event_catalog import (
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
                        args=str(args)[:200] if args else "",
                        kwargs=str(kwargs)[:200] if kwargs else "",
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
                            error=str(e)[:200],
                        ),
                        logger,
                    )
                    raise
                else:
                    emit_progress(
                        make_subagent_tool_completed(
                            subagent_name,
                            tool=tool_name,
                            result_preview=str(result)[:300] if result else "",
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
                args=str(args)[:200] if args else "",
                kwargs=str(kwargs)[:200] if kwargs else "",
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
                    error=str(e)[:200],
                ),
                logger,
            )
            raise
        else:
            emit_progress(
                make_subagent_tool_completed(
                    subagent_name,
                    tool=tool_name,
                    result_preview=str(result)[:300] if result else "",
                ),
                logger,
            )
            return result

    return logged_callable


def wrap_main_agent_tool_with_logging(
    tool: BaseTool | Callable[..., Any],
    logger: logging.Logger,
    *,
    tool_group: str | None = None,
) -> BaseTool | Callable[..., Any]:
    """Wrap a main agent tool to emit progress events on invocation.

    Uses event pattern: ``soothe.tool.<group>.<tool>_started`` when
    *tool_group* is provided, otherwise ``soothe.tool.<tool>.started``.

    Args:
        tool: The tool to wrap (BaseTool or callable).
        logger: Logger instance for the main agent.
        tool_group: User-facing tool group name (e.g. ``websearch``).

    Returns:
        Wrapped tool that logs invocation and results.
    """
    from langchain_core.tools import BaseTool

    from soothe.core.event_catalog import make_tool_completed, make_tool_failed, make_tool_started
    from soothe.utils.progress import emit_progress

    if hasattr(tool, "_soothe_progress_wrapped") and tool._soothe_progress_wrapped:
        return tool

    tool_name = tool.name if isinstance(tool, BaseTool) else getattr(tool, "__name__", "unknown")

    # Skip wrapper for tools that emit their own detailed progress events
    # These tools already emit domain-specific events with richer context
    _tools_with_own_progress = {
        "run_command",  # Emits CommandStartedEvent, CommandCompletedEvent, etc.
        "run_python",  # Emits PythonExecutionStartedEvent, PythonExecutionCompletedEvent
        "run_background",  # Emits BackgroundProcessStartedEvent
        "kill_process",  # Emits ProcessKilledEvent
    }
    if tool_name in _tools_with_own_progress:
        tool._soothe_progress_wrapped = True
        return tool

    def _started(**extra: Any) -> dict[str, Any]:
        return make_tool_started(tool_name, tool_group=tool_group, **extra)

    def _completed(**extra: Any) -> dict[str, Any]:
        return make_tool_completed(tool_name, tool_group=tool_group, **extra)

    def _failed(**extra: Any) -> dict[str, Any]:
        return make_tool_failed(tool_name, tool_group=tool_group, **extra)

    if isinstance(tool, BaseTool):
        if hasattr(tool, "func") and tool.func is not None:
            original_func = tool.func

            def logged_func(*args: Any, **kwargs: Any) -> Any:
                emit_progress(
                    _started(args=kwargs or {}),
                    logger,
                )
                try:
                    result = original_func(*args, **kwargs)
                except Exception as e:
                    emit_progress(_failed(error=str(e)[:200]), logger)
                    raise
                else:
                    emit_progress(_completed(result_preview=str(result)[:300] if result else ""), logger)
                    return result

            tool.func = logged_func
            tool._soothe_progress_wrapped = True
            return tool

        if hasattr(tool, "_run"):
            original_run = tool._run

            @functools.wraps(original_run)
            def logged_run(*args: Any, **kwargs: Any) -> Any:
                emit_progress(
                    _started(args=kwargs or {}),
                    logger,
                )
                try:
                    result = original_run(*args, **kwargs)
                except Exception as e:
                    emit_progress(_failed(error=str(e)[:200]), logger)
                    raise
                else:
                    emit_progress(_completed(result_preview=str(result)[:300] if result else ""), logger)
                    return result

            tool._run = logged_run
            tool._soothe_progress_wrapped = True

            if hasattr(tool, "_arun"):
                original_arun = tool._arun

                @functools.wraps(original_arun)
                async def logged_arun(*args: Any, **kwargs: Any) -> Any:
                    emit_progress(
                        _started(args=kwargs or {}),
                        logger,
                    )
                    try:
                        result = await original_arun(*args, **kwargs)
                    except Exception as e:
                        emit_progress(_failed(error=str(e)[:200]), logger)
                        raise
                    else:
                        emit_progress(_completed(result_preview=str(result)[:300] if result else ""), logger)
                        return result

                tool._arun = logged_arun

            return tool

        logger.debug("Tool %s has no 'func' or '_run' attribute, skipping logging wrapper", tool_name)
        return tool

    def logged_callable(*args: Any, **kwargs: Any) -> Any:
        emit_progress(
            _started(args=str(args)[:200] if args else "", kwargs=str(kwargs)[:200] if kwargs else ""),
            logger,
        )
        try:
            result = tool(*args, **kwargs)
        except Exception as e:
            emit_progress(_failed(error=str(e)[:200]), logger)
            raise
        else:
            emit_progress(_completed(result_preview=str(result)[:300] if result else ""), logger)
            return result

    logged_callable._soothe_progress_wrapped = True
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
