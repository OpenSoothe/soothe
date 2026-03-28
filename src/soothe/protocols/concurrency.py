"""ConcurrencyPolicy -- parallel execution control (RFC-0002 Module 7)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ConcurrencyPolicy(BaseModel):
    """Controls parallel execution of goals, plan steps, subagents, and tools.

    All concurrency limits support ``0`` as a special value meaning "unlimited".
    When set to 0, the corresponding concurrency layer disables its semaphore
    and allows unbounded parallel execution.

    Args:
        max_parallel_goals: Maximum goals running simultaneously (autonomous mode).
            Set to 0 for unlimited concurrent goals.
        max_parallel_steps: Maximum plan steps running simultaneously.
            Set to 0 for unlimited concurrent steps.
        max_parallel_subagents: Maximum subagents running simultaneously.
            Reserved for future ConcurrencyMiddleware enforcement.
            Set to 0 for unlimited concurrent subagents.
        max_parallel_tools: Maximum tool calls running simultaneously.
            Controls ParallelToolNode concurrency for parallel tool execution.
            Set to 0 for unlimited concurrent tool calls.
        global_max_llm_calls: Cross-level circuit breaker limiting total
            concurrent LLM invocations across all goals and steps.
            Set to 0 to disable the circuit breaker (use with caution).
        step_parallelism: Scheduling strategy for plan steps.
            ``sequential`` always runs one step at a time.
            ``dependency`` runs independent steps in parallel (DAG-aware).
            ``max`` runs all non-blocked steps in parallel.
    """

    max_parallel_goals: int = 1
    max_parallel_steps: int = 1
    max_parallel_subagents: int = 1
    max_parallel_tools: int = Field(
        default=10,
        description="Maximum tool calls running simultaneously. "
        "Set to 1 for sequential execution, 3-5 for conservative parallelism, "
        "10 for balanced API usage, 20+ for high-limit APIs. "
        "Set to 0 for unlimited. "
        "LangGraph default is unlimited; this provides sensible default.",
    )
    global_max_llm_calls: int = 5
    step_parallelism: Literal["sequential", "dependency", "max"] = "dependency"
