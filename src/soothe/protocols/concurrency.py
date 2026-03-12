"""ConcurrencyPolicy -- parallel execution control (RFC-0002 Module 7)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ConcurrencyPolicy(BaseModel):
    """Controls parallel execution of plan steps, subagents, and tools.

    Args:
        max_parallel_subagents: Maximum subagents running simultaneously.
        max_parallel_tools: Maximum tool calls running simultaneously.
        max_parallel_steps: Maximum plan steps running simultaneously.
        step_parallelism: Scheduling strategy for plan steps.
    """

    max_parallel_subagents: int = 1
    max_parallel_tools: int = 3
    max_parallel_steps: int = 1
    step_parallelism: Literal["sequential", "dependency", "max"] = "dependency"
