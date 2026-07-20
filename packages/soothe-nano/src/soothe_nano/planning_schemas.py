"""Planning schema types shared by CoreAgent prompts (subset of StrangeLoop models)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GoalComponentStatus(BaseModel):
    """One decomposed facet of the current GOAL and its evidence state."""

    component: str = Field(max_length=120)
    status: Literal["not_started", "partial", "satisfied", "blocked"]
    evidence: str = Field(default="", max_length=2048)
    gap: str = Field(default="", max_length=2048)


class PlanGapAnalysis(BaseModel):
    """Explicit evidence inventory + distance from GOAL (feeds plan-assess)."""

    components: list[GoalComponentStatus] = Field(min_length=1, max_length=8)
    evidence_summary: str = Field(max_length=2048)
    remaining_gaps: list[str] = Field(default_factory=list, max_length=6)
    distance_from_goal: Literal["far", "moderate", "near", "at_goal"]
    gap_reasoning: str = Field(max_length=2048)


class ToolCallHead(BaseModel):
    """One tool invocation captured from the most recent execute wave."""

    name: str = Field(max_length=64)
    head: str = Field(default="", max_length=120)


class WaveStepProgress(BaseModel):
    """One executed step row in the most recent wave."""

    step_id: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=500)
    status: Literal["completed", "failed", "unknown"] = "unknown"
    outcome_preview: str = Field(default="", max_length=200)


class PriorProgressDigest(BaseModel):
    """Compact snapshot of the most recent execute wave."""

    iteration: int
    wave_index: int = 0
    steps_completed: int = 0
    steps_failed: int = 0
    tool_calls: list[ToolCallHead] = Field(default_factory=list, max_length=8)
    evidence_excerpts: list[str] = Field(default_factory=list, max_length=3)
    step_summaries: list[WaveStepProgress] = Field(default_factory=list, max_length=8)
    derived_progress_hint: Literal["none", "low", "medium", "high"] = "low"


__all__ = [
    "GoalComponentStatus",
    "PlanGapAnalysis",
    "PriorProgressDigest",
    "ToolCallHead",
    "WaveStepProgress",
]
