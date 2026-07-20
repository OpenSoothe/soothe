"""Projection config bounds for Context Engine settings (RFC-624).

Full ContextEngine lives in soothe; nano only needs the config dataclass
referenced by ``soothe_nano.config`` models.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProjectionConfig(BaseModel):
    """Limits for bounded projection."""

    max_goals: int = 5
    max_steps_per_goal: int = 10
    max_ledger_chars: int = 4000
    max_ledger_messages: int = 20
    max_lineage_chars: int = 2000
    max_project_instructions_chars: int = 8000


class PriorGoalSummary(BaseModel):
    """Condensed summary of a completed goal for cross-goal context."""

    goal_id: str = ""
    description: str = ""
    status: str = ""
    step_summary: str = ""
    completion_text: str = ""
    total_duration_ms: int = 0
    total_tokens_used: int = 0


class ContextBundle(BaseModel):
    """Structured output of ContextEngine.project() for prompt templates."""

    prior_goals: list[PriorGoalSummary] = Field(default_factory=list)
    project_instructions: str = ""


__all__ = ["ContextBundle", "PriorGoalSummary", "ProjectionConfig"]
