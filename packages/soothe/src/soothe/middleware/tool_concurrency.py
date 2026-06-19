"""Middleware to limit concurrent tool calls per thread (IG-478).

LangChain's ToolNode uses asyncio.gather for parallel tool execution without limits.
This middleware intercepts each tool call via awrap_tool_call and acquires a semaphore
slot before execution, naturally bounding parallel tool calls.

The limit prevents:
- API rate limit exhaustion from parallel tool calls
- Resource starvation in high-concurrency scenarios
- Timeout cascades when many tools compete for I/O
"""

from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from soothe.middleware.tool_call_args_registry import (
    init_tool_call_args_registry,
    record_tool_call_args_from_request,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langgraph.types import Command

logger = logging.getLogger(__name__)

# Thread-local semaphore for tool concurrency (per asyncio.Task / thread_id)
# Each thread/task gets its own independent limit
_tool_semaphore: ContextVar[asyncio.Semaphore | None] = ContextVar("tool_semaphore", default=None)

# Default limit for concurrent tool calls
DEFAULT_MAX_PARALLEL_TOOLS = 5


class ToolConcurrencyMiddleware(AgentMiddleware):
    """Middleware limiting concurrent tool calls per thread.

    LangChain's ToolNode uses asyncio.gather to run tools in parallel. This middleware
    intercepts each tool call via `awrap_tool_call` and acquires a semaphore slot before
    execution. When ToolNode runs N tools concurrently, they all contend for semaphore
    slots, naturally bounding parallelism.

    The semaphore is thread-local (ContextVar), so different threads/tasks have
    independent limits. Call `init_tool_concurrency_for_thread()` at the start of
    each StrangeLoop/CoreAgent stream to set the limit.

    Note: This middleware does NOT have a constructor with limit parameter because
    the limit is set per-thread via ContextVar, not per-middleware instance.
    The middleware instance is shared across all threads.
    """

    name = "ToolConcurrencyMiddleware"

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Acquire semaphore slot before tool execution.

        Args:
            request: The tool call request.
            handler: The next handler (actual tool execution).

        Returns:
            Tool execution result.
        """
        record_tool_call_args_from_request(request)
        sem = get_tool_semaphore()
        if sem is None:
            # Unlimited mode (limit=0 or not initialized)
            return await handler(request)

        async with sem:
            return await handler(request)


def get_tool_semaphore() -> asyncio.Semaphore | None:
    """Get the current thread-local tool semaphore.

    Returns:
        Semaphore for current thread, or None if unlimited.
    """
    return _tool_semaphore.get()


def set_tool_semaphore(sem: asyncio.Semaphore | None) -> None:
    """Set the thread-local tool semaphore directly.

    Args:
        sem: Semaphore instance or None for unlimited.
    """
    _tool_semaphore.set(sem)


def init_tool_concurrency_for_thread(limit: int = DEFAULT_MAX_PARALLEL_TOOLS) -> None:
    """Initialize tool concurrency semaphore for the current thread.

    Call this at the start of StrangeLoop execution or CoreAgent stream to
    establish a per-thread concurrency budget.

    Args:
        limit: Maximum concurrent tool calls (default: 5). 0 = unlimited.
    """
    init_tool_call_args_registry()
    if limit <= 0:
        set_tool_semaphore(None)
        logger.debug("[ToolConcurrency] Thread semaphore disabled (unlimited)")
    else:
        set_tool_semaphore(asyncio.Semaphore(limit))
        logger.debug("[ToolConcurrency] Thread semaphore initialized: limit=%d", limit)
