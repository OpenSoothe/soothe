"""Shared routing classification models for CoreAgent execution paths."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class TaskComplexity(StrEnum):
    """Unified task complexity levels for routing decisions.

    - minimal: No tools needed (direct reply)
    - simple: Single focused step
    - medium: Multi-step with moderate tool use
    - complex: Architecture, migration, deep multi-phase work
    """

    MINIMAL = "minimal"
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


class RoutingClassification(BaseModel):
    """Routing complexity classification for execution path selection.

    Args:
        task_complexity: Routing complexity level.
        preferred_subagent: Wire or host hint for which subagent to prefer.
        routing_hint: Routing strategy hint.
    """

    task_complexity: TaskComplexity = Field(
        description="Routing complexity: minimal (no tools), simple, medium, or complex"
    )
    preferred_subagent: str | None = Field(
        default=None,
        description="Preferred subagent name when the host requests a specialist",
    )
    routing_hint: str | None = Field(
        default=None,
        description="Routing strategy hint: 'subagent', 'tool', 'llm_only', etc.",
    )


__all__ = ["RoutingClassification", "TaskComplexity"]
