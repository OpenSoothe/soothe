"""ConcurrencyController -- hierarchical concurrency enforcement (RFC-0009).

Provides semaphore-based concurrency control at four levels:
goal scheduling, step scheduling, tool execution, and global LLM call budget.
Created once in ``SootheRunner.__init__`` and shared across all
execution paths.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.protocols.concurrency import ConcurrencyPolicy

logger = logging.getLogger(__name__)


class ConcurrencyController:
    """Hierarchical concurrency enforcement via semaphores.

    Controls parallel execution at four levels:

    - **Goal level** (autonomous mode): limits concurrent goal executions.
    - **Step level** (within a goal's plan): limits concurrent step executions.
    - **Tool level** (within a step): limits concurrent tool calls.
    - **LLM call level** (global circuit breaker): caps total concurrent
      LangGraph invocations across all goals and steps to prevent API
      rate-limit exhaustion.

    Args:
        policy: Concurrency limits configuration.
    """

    def __init__(self, policy: ConcurrencyPolicy) -> None:
        """Initialize with concurrency limits from policy."""
        self._policy = policy
        self._goal_sem = asyncio.Semaphore(policy.max_parallel_goals)
        self._step_sem = asyncio.Semaphore(policy.max_parallel_steps)
        self._llm_sem = asyncio.Semaphore(policy.global_max_llm_calls)
        self._tool_sem = asyncio.Semaphore(policy.max_parallel_tools)

    @asynccontextmanager
    async def acquire_goal(self) -> AsyncGenerator[None]:
        """Acquire a goal execution slot.

        Yields:
            None -- releases the slot on exit.
        """
        async with self._goal_sem:
            yield

    @asynccontextmanager
    async def acquire_step(self) -> AsyncGenerator[None]:
        """Acquire a step execution slot.

        Yields:
            None -- releases the slot on exit.
        """
        async with self._step_sem:
            yield

    @asynccontextmanager
    async def acquire_llm_call(self) -> AsyncGenerator[None]:
        """Acquire a global LLM call slot (circuit breaker).

        This is the cross-level budget that prevents goals * steps from
        exhausting API rate limits.

        Yields:
            None -- releases the slot on exit.
        """
        async with self._llm_sem:
            yield

    @asynccontextmanager
    async def acquire_tool(self) -> AsyncGenerator[None]:
        """Acquire a tool execution slot.

        Controls parallel execution of tool calls within a single LLM invocation.

        Yields:
            None -- releases the slot on exit.
        """
        async with self._tool_sem:
            yield

    @property
    def policy(self) -> ConcurrencyPolicy:
        """The active concurrency policy."""
        return self._policy

    @property
    def step_parallelism(self) -> str:
        """The step parallelism mode."""
        return self._policy.step_parallelism

    @property
    def max_parallel_steps(self) -> int:
        """Maximum parallel steps allowed."""
        return self._policy.max_parallel_steps

    @property
    def max_parallel_goals(self) -> int:
        """Maximum parallel goals allowed."""
        return self._policy.max_parallel_goals

    @property
    def max_parallel_tools(self) -> int:
        """Maximum parallel tools allowed."""
        return self._policy.max_parallel_tools
