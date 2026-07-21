"""ConcurrencyPolicy -- parallel execution control."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ConcurrencyPolicy(BaseModel):
    """Controls parallel execution of goals, plan steps, subagents, and tools.

    All concurrency limits support ``0`` as a special value meaning "unlimited".
    When set to 0, the corresponding concurrency layer disables its semaphore
    and allows unbounded parallel execution.

    Args:
        max_parallel_goals: Maximum goals running simultaneously (autonomous mode).
            Set to 0 for unlimited concurrent goals.
        max_parallel_steps: Max plan steps concurrent in one batch; the runner / agent-loop
            executor repeats batches until the plan wave is done. Set to 0 for unlimited.
        max_parallel_subagents: Maximum subagents running simultaneously.
            Reserved for future ConcurrencyMiddleware enforcement.
            Set to 0 for unlimited concurrent subagents.
        global_max_llm_calls: Cross-level circuit breaker limiting total
            concurrent LLM invocations across all goals and steps.
            Set to 0 to disable the circuit breaker (use with caution).
        step_parallelism: Scheduling strategy for plan steps.
            ``sequential`` always runs one step at a time.
            ``dependency`` runs independent steps in parallel (DAG-aware).
            ``max`` runs all non-blocked steps in parallel.

    Note: Tool parallelism is handled by langchain's built-in asyncio.gather
    in ToolNode. No explicit max_parallel_tools configuration needed.
    """

    max_parallel_goals: int = 1
    max_parallel_steps: int = 2
    max_parallel_subagents: int = 4
    global_max_llm_calls: int = 5
    step_parallelism: Literal["sequential", "dependency", "max"] = "dependency"
