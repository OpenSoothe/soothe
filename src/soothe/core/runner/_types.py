"""Shared types and utilities for SootheRunner."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel


def _generate_thread_id() -> str:
    """Generate an 8-char hex thread ID (matching deepagents convention)."""
    return uuid.uuid4().hex[:8]


class IterationRecord(BaseModel):
    """Structured record of a single autonomous iteration (RFC-0007).

    Args:
        iteration: Zero-based iteration index.
        goal_id: Goal being worked on.
        plan_summary: Brief description of the plan at this iteration.
        actions_summary: Truncated agent response text.
        reflection_assessment: Planner's reflection assessment.
        outcome: Whether the iteration continues, completes, or fails.
    """

    iteration: int
    goal_id: str
    plan_summary: str
    actions_summary: str
    reflection_assessment: str
    outcome: str  # Literal["continue", "goal_complete", "failed"]


class AgenticIterationRecord(BaseModel):
    """Structured record of a single agentic iteration (RFC-0008).

    Args:
        iteration: Zero-based iteration index.
        planning_strategy: Strategy used ("none" | "lightweight" | "comprehensive").
        observation_summary: Summary of observation phase results.
        actions_taken: Truncated agent response text.
        verification_result: Verification decision and reasoning.
        should_continue: Whether loop continued after this iteration.
        duration_ms: Duration of the iteration in milliseconds.
    """

    iteration: int
    planning_strategy: Literal["none", "lightweight", "comprehensive"]
    observation_summary: str
    actions_taken: str
    verification_result: str
    should_continue: bool
    duration_ms: int


@dataclass
class RunnerState:
    """Mutable state accumulated during a single query execution."""

    thread_id: str = ""
    full_response: list[str] = field(default_factory=list)
    plan: Any = None  # Type: Plan | None
    context_projection: Any = None
    recalled_memories: list[Any] = field(default_factory=list)
    seen_message_ids: set[str] = field(default_factory=set)
    stream_error: str | None = None
    unified_classification: Any = None  # Type: UnifiedClassification
    cached_routing: Any = None  # Cached classification result for reuse
    iteration_records: list[Any] = field(default_factory=list)  # AgenticIterationRecord list
