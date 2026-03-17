"""ConcurrencyPolicy -- parallel execution control (RFC-0002 Module 7)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ConcurrencyPolicy(BaseModel):
    """Controls parallel execution of goals, plan steps, subagents, and tools.

    Args:
        max_parallel_goals: Maximum goals running simultaneously (autonomous mode).
        max_parallel_steps: Maximum plan steps running simultaneously.
        max_parallel_subagents: Maximum subagents running simultaneously.
            Reserved for future ConcurrencyMiddleware enforcement.
        max_parallel_tools: Maximum tool calls running simultaneously.
            Reserved for future ConcurrencyMiddleware enforcement.
        global_max_llm_calls: Cross-level circuit breaker limiting total
            concurrent LLM invocations across all goals and steps.
        step_parallelism: Scheduling strategy for plan steps.
            ``sequential`` always runs one step at a time.
            ``dependency`` runs independent steps in parallel (DAG-aware).
            ``max`` runs all non-blocked steps in parallel.
    """

    max_parallel_goals: int = 1
    max_parallel_steps: int = 1
    max_parallel_subagents: int = 1
    max_parallel_tools: int = 3
    global_max_llm_calls: int = 5
    step_parallelism: Literal["sequential", "dependency", "max"] = "dependency"
