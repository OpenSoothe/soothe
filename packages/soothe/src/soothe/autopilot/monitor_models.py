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
