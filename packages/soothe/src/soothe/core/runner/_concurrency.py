"""ConcurrencyController -- hierarchical concurrency enforcement (RFC-0009).

Provides semaphore-based concurrency control at three levels:
goal scheduling, step scheduling, and global LLM call budget.
Created once in ``SootheRunner.__init__`` and shared across all
execution paths.

Note: Tool parallelism is handled by langchain's built-in asyncio.gather
in ToolNode. No explicit tool semaphore needed.
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

    Controls parallel execution at three levels:

    - **Goal level** (autonomous mode): limits concurrent goal executions.
    - **Step level** (within a goal's plan): limits concurrent step executions.
    - **LLM call level** (global circuit breaker): caps total concurrent
      LangGraph invocations across all goals and steps to prevent API
      rate-limit exhaustion.

    Note: Tool parallelism is handled by langchain's ToolNode via
    asyncio.gather. No tool-level semaphore needed here.

    Args:
        policy: Concurrency limits configuration.
    """

    def __init__(self, policy: ConcurrencyPolicy) -> None:
        """Initialize with concurrency limits from policy.

        Special behavior: When a limit is set to 0 (unlimited), no semaphore
        is created for that layer, allowing unbounded parallel execution.
        """
        self._policy = policy
        # Create semaphores only for positive limits (0 = unlimited)
        self._goal_sem = (
            asyncio.Semaphore(policy.max_parallel_goals) if policy.max_parallel_goals > 0 else None
        )
        self._step_sem = (
            asyncio.Semaphore(policy.max_parallel_steps) if policy.max_parallel_steps > 0 else None
        )
        self._llm_sem = (
            asyncio.Semaphore(policy.global_max_llm_calls)
            if policy.global_max_llm_calls > 0
            else None
        )

    @asynccontextmanager
    async def acquire_goal(self) -> AsyncGenerator[None]:
        """Acquire a goal execution slot.

        Unlimited mode (limit=0): No semaphore, passes through immediately.
        Limited mode: Acquires semaphore, blocks if limit reached.

        Yields:
            None -- releases the slot on exit (if semaphore exists).
        """
        if self._goal_sem is None:
            # Unlimited: no blocking
            yield
        else:
            # Limited: acquire semaphore
            async with self._goal_sem:
                yield

    @asynccontextmanager
    async def acquire_step(self) -> AsyncGenerator[None]:
        """Acquire a step execution slot.

        Unlimited mode (limit=0): No semaphore, passes through immediately.
        Limited mode: Acquires semaphore, blocks if limit reached.

        Yields:
            None -- releases the slot on exit (if semaphore exists).
        """
        if self._step_sem is None:
            # Unlimited: no blocking
            yield
        else:
            # Limited: acquire semaphore
            async with self._step_sem:
                yield

    @asynccontextmanager
    async def acquire_llm_call(self) -> AsyncGenerator[None]:
        """Acquire a global LLM call slot (circuit breaker).

        Unlimited mode (limit=0): Circuit breaker disabled, passes through.
        Limited mode: Acquires semaphore, blocks if global limit reached.

        This is the cross-level budget that prevents goals * steps from
        exhausting API rate limits.

        Yields:
            None -- releases the slot on exit (if semaphore exists).
        """
        if self._llm_sem is None:
            # Unlimited: circuit breaker disabled
            yield
        else:
            # Limited: acquire semaphore
            async with self._llm_sem:
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
    def has_goal_limit(self) -> bool:
        """Check if goal concurrency is limited (semaphore exists)."""
        return self._goal_sem is not None

    @property
    def has_step_limit(self) -> bool:
        """Check if step concurrency is limited (semaphore exists)."""
        return self._step_sem is not None

    @property
    def has_llm_limit(self) -> bool:
        """Check if LLM call circuit breaker is active (semaphore exists)."""
        return self._llm_sem is not None
