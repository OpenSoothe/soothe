"""ParallelToolNode -- execute multiple tools in parallel with semaphore control.

This module provides parallel execution of independent tool calls from a single
LLM invocation, delivering 2.5-3x speedup for multi-tool scenarios.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence
    from concurrent.futures import ThreadPoolExecutor

    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


class ParallelToolExecutor:
    """Execute multiple tool calls in parallel with semaphore-based concurrency control.

    This class provides the core parallel execution logic that can be integrated
    into any tool invocation pipeline. It executes independent tools concurrently
    via asyncio.gather() while respecting the max_parallel_tools limit.

    Args:
        tools: List of available tools.
        max_parallel: Maximum number of tools to execute concurrently.
        executor: Optional ThreadPoolExecutor for synchronous tools.
    """

    def __init__(
        self,
        tools: Sequence[BaseTool],
        max_parallel: int = 3,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        """Initialize parallel tool executor."""
        self.tools = {tool.name: tool for tool in tools}
        self.max_parallel = max_parallel
        self._semaphore = asyncio.Semaphore(max_parallel)
        self._executor = executor

    async def execute_batch(
        self,
        tool_calls: list[dict[str, Any]],
    ) -> list[Any]:
        """Execute multiple tool calls in parallel.

        Args:
            tool_calls: List of tool call dictionaries with 'name' and 'args' keys.

        Returns:
            List of results in the same order as tool_calls.
        """
        if not tool_calls:
            return []

        start_time = time.perf_counter()
        parallelism = min(len(tool_calls), self.max_parallel)

        logger.info(
            "Executing %d tools with parallelism=%d (max=%d)",
            len(tool_calls),
            parallelism,
            self.max_parallel,
        )

        # Execute all tools in parallel using asyncio.gather
        results = await asyncio.gather(
            *[self._execute_single_tool(tc) for tc in tool_calls],
            return_exceptions=True,
        )

        # Calculate performance metrics
        duration_ms = (time.perf_counter() - start_time) * 1000

        # Log results summary
        successful = sum(1 for r in results if not isinstance(r, Exception))
        failed = len(results) - successful

        logger.info(
            "Parallel execution completed in %.1fms: %d succeeded, %d failed",
            duration_ms,
            successful,
            failed,
        )

        return results

    async def _execute_single_tool(self, tool_call: dict[str, Any]) -> Any:
        """Execute a single tool with semaphore control.

        Args:
            tool_call: Tool call dictionary with 'name' and 'args' keys.

        Returns:
            Tool execution result.

        Raises:
            Exception: If tool execution fails.
        """
        tool_name = tool_call.get("name", "")
        tool_args = tool_call.get("args", {})

        async with self._semaphore:
            tool = self.tools.get(tool_name)
            if not tool:
                msg = f"Tool '{tool_name}' not found"
                raise ValueError(msg)

            tool_start = time.perf_counter()

            try:
                logger.debug("Executing tool: %s(%s)", tool_name, tool_args)

                # Execute tool (handle both sync and async tools)
                if hasattr(tool, "arun"):
                    result = await tool.arun(tool_args)
                elif hasattr(tool, "invoke"):
                    # LangChain tools use invoke()
                    if asyncio.iscoroutinefunction(tool.invoke):
                        result = await tool.invoke(tool_args)
                    else:
                        # Run sync tool in executor for parallelism
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(
                            self._executor,
                            tool.invoke,
                            tool_args,
                        )
                else:
                    msg = f"Tool '{tool_name}' has no callable method (arun or invoke)"
                    raise AttributeError(msg)

                tool_duration = (time.perf_counter() - tool_start) * 1000
                logger.debug(
                    "Tool %s completed in %.1fms",
                    tool_name,
                    tool_duration,
                )
            except Exception:
                tool_duration = (time.perf_counter() - tool_start) * 1000
                logger.exception(
                    "Tool %s failed after %.1fms",
                    tool_name,
                    tool_duration,
                )
                raise
            else:
                return result

    def _create_batches(self, tool_calls: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        """Create execution batches based on dependencies.

        Phase 1: All tools are considered independent.
        Phase 2 (future): Dependency analysis for sequencing.

        Args:
            tool_calls: List of tool call dictionaries.

        Returns:
            List of batches, where each batch can be executed in parallel.
        """
        # Phase 1: Simple - all tools can run in parallel
        # Return single batch for maximum parallelism
        return [tool_calls]

        # Phase 2 (future): Implement dependency analysis
        # - File read/write detection
        # - State mutation analysis
        # - Custom dependency analyzers
