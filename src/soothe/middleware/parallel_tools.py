"""ParallelToolsMiddleware -- control parallel tool execution with semaphore.

This middleware intercepts tool execution to limit concurrent invocation
of multiple tools from a single LLM response using semaphore-based control.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from langchain.agents.middleware import AgentMiddleware

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.messages import ToolMessage
    from langgraph.prebuilt.tool_node import ToolCallRequest
    from langgraph.types import Command

logger = logging.getLogger(__name__)


class ParallelToolsMiddleware(AgentMiddleware):
    """Middleware to control parallel tool execution with semaphore.

    LangGraph ToolNode executes all tool calls from a single LLM response
    in parallel via asyncio.gather() with unlimited parallelism. This middleware
    uses awrap_tool_call hook to limit concurrent execution with a semaphore.

    Args:
        max_parallel_tools: Maximum number of tools to execute concurrently.
            Default is 10 for balanced API usage. LangGraph default is unlimited.
    """

    def __init__(self, max_parallel_tools: int = 10) -> None:
        """Initialize parallel tools middleware with semaphore."""
        self.max_parallel_tools = max_parallel_tools
        self._semaphore = asyncio.Semaphore(max_parallel_tools)
        logger.info(
            "ParallelToolsMiddleware initialized: max_parallel_tools=%d (LangGraph default: unlimited)",
            max_parallel_tools,
        )

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Control tool execution with semaphore.

        This hook is called for each tool during parallel batch execution.
        LangGraph's asyncio.gather() launches all tools simultaneously,
        but the semaphore limits how many can proceed concurrently.

        Args:
            request: Tool call request with tool_call, tool, state, runtime.
            handler: Callable that executes the tool (can be called multiple times for retries).

        Returns:
            ToolMessage or Command from tool execution.
        """
        tool_name = request.tool_call.get("name", "unknown")

        # Calculate active slots for logging
        active_count = self.max_parallel_tools - self._semaphore._value
        logger.debug(
            "Tool %s: %d/%d parallel slots active, waiting for slot",
            tool_name,
            active_count,
            self.max_parallel_tools,
        )

        # Acquire semaphore slot (wait if limit reached)
        async with self._semaphore:
            active_count = self.max_parallel_tools - self._semaphore._value
            logger.debug(
                "Tool %s: acquired slot (%d/%d active), executing",
                tool_name,
                active_count,
                self.max_parallel_tools,
            )

            # Execute tool (handler can be called multiple times for retries)
            result = await handler(request)

            logger.debug("Tool %s: completed, releasing slot", tool_name)
            return result
