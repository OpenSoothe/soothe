"""Models for AutopilotMonitor (RFC-625)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

# ── Goal Intake ───────────────────────────────────────────────────────────────


class GoalIntakeResult(BaseModel):
    """Result of goal intake through GoalIntakeHandler."""

    status: Literal["accepted", "rejected", "skipped"]
    goal_id: str | None = None
    reason: str | None = None
    adjusted_priority: int | None = None
    suggested_dependencies: list[str] = []


class GoalPlacement(BaseModel):
    """LLM-driven placement analysis for new goal."""

    adjusted_priority: int = 50
    suggested_dependencies: list[str] = []
    suggested_informs: list[str] = []
    merge_with: str | None = None  # Goal ID to merge with
    estimated_complexity: Literal["simple", "moderate", "complex"] = "moderate"
    reasoning: str = ""


# ── DAG Verification ───────────────────────────────────────────────────────────


@dataclass
class MergeSuggestion:
    """Suggestion to merge multiple goals."""

    goal_ids: list[str]
    merged_description: str


@dataclass
class DecomposeSuggestion:
    """Suggestion to decompose a goal into sub-goals."""

    goal_id: str
    subgoals: list[dict[str, Any]]  # [{description, priority, depends_on}]


@dataclass
class DagHealthReport:
    """LLM-driven DAG health verification report."""

    suggest_reset: list[str] = field(default_factory=list)  # Goal IDs to reset
    suggest_remove: list[str] = field(default_factory=list)  # Goal IDs to remove
    suggest_merge: list[MergeSuggestion] = field(default_factory=list)
    suggest_decompose: list[DecomposeSuggestion] = field(default_factory=list)
    suggest_priority_adjust: dict[str, int] = field(default_factory=dict)
    reasoning: str = ""
    errors: list[str] = field(default_factory=list)


# ── Dreaming ───────────────────────────────────────────────────────────────────


DreamingMode = Literal["episodic", "procedure", "semantic", "profile"]
DreamingScope = Literal["loop", "workspace", "topic"]


@dataclass
class DreamingContext:
    """Context gathered for dreaming distillation."""

    goals: list[Any]  # list[GoalNode]
    ledger: list[tuple[Any, str | None]]  # list[(BaseMessage, phase)]
    scope_id: str  # loop_id, workspace path, or topic name


class EpisodeSpec(BaseModel):
    """Episode extracted by LLM distillation."""

    goal_id: str
    description: str
    outcome_summary: str
    key_steps: list[str] = []
    lessons_learned: str = ""


class ProcedureSpec(BaseModel):
    """Reusable procedure extracted by LLM distillation."""

    name: str
    description: str
    trigger_conditions: list[str] = []
    steps: list[str] = []
    tools_used: list[str] = []


class SemanticUpdate(BaseModel):
    """MEMORY.md update extracted by LLM distillation."""

    additions: list[str] = []  # New sections
    modifications: dict[str, str] = {}  # Section → updated content
    sections_to_update: list[str] = []


class ProfileUpdate(BaseModel):
    """User profile update extracted by LLM distillation."""

    communication_style: str = ""
    preferences: list[str] = []
    recurring_goals: list[str] = []
    expertise_level: Literal["beginner", "intermediate", "advanced", "expert"] = "intermediate"


# ── Mode Switch ─────────────────────────────────────────────────────────────────


class ModeSwitchResult(BaseModel):
    """Result of autopilot mode toggle."""

    loop_id: str
    enabled: bool
    message: str = ""
