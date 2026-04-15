"""Shared types and utilities for SootheRunner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel


def _generate_thread_id() -> str:
    """Generate a 12-char alphanumeric thread ID.

    Uses base36 encoding (0-9, a-z) for compact, human-readable IDs.
    """
    import secrets

    # Generate 12 random characters from base36 alphabet
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    return "".join(secrets.choice(alphabet) for _ in range(12))


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


class GoalResult(BaseModel):
    """Result from AgentLoop execution for autonomous goal reflection (RFC-200, IG-154).

    Wraps PlanResult from AgentLoop for autonomous goal reflection.

    Args:
        goal_id: Goal identifier
        status: Execution status (completed, failed, in_progress)
        evidence_summary: Accumulated evidence from AgentLoop execution
        goal_progress: Progress percentage (0.0-1.0)
        confidence: Model confidence in result (0.0-1.0)
        full_output: Final answer when status is completed
        iteration_count: Number of AgentLoop iterations used
        duration_ms: Total execution duration in milliseconds
    """

    goal_id: str
    status: Literal["completed", "failed", "in_progress"]
    evidence_summary: str = ""
    goal_progress: float = 0.0
    confidence: float = 0.8
    full_output: str | None = None
    iteration_count: int = 0
    duration_ms: int = 0


@dataclass
class RunnerState:
    """Mutable state accumulated during a single query execution."""

    thread_id: str = ""
    langgraph_thread_id: str | None = None  # LangGraph id when parallel goals/steps need isolation
    workspace: str | None = None  # Thread-specific workspace (RFC-103)
    full_response: list[str] = field(default_factory=list)
    plan: Any = None  # Type: Plan | None
    context_projection: Any = None
    recalled_memories: list[Any] = field(default_factory=list)
    seen_message_ids: set[str] = field(default_factory=set)
    stream_error: str | None = None
    unified_classification: Any = None  # Type: UnifiedClassification
    cached_routing: Any = None  # Cached classification result for reuse
    iteration_records: list[Any] = field(default_factory=list)  # AgenticIterationRecord list
    observation_refresh_needed: bool = False
    observation_scope_key: str = ""
    # Context for system prompt XML injection (RFC-104)
    git_status: dict[str, Any] | None = None
    thread_context: dict[str, Any] = field(default_factory=dict)
    protocol_summary: dict[str, Any] = field(default_factory=dict)
    # Per-query artifact store (RFC-0010); avoids sharing one RunArtifactStore on the runner (IG-110)
    artifact_store: Any = None
    # Thread context for subagents (IG-140)
    prior_messages: str | None = None
