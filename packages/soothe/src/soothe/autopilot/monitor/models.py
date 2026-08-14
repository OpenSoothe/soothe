"""Models for AutopilotMonitor (RFC-625)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

# ── Goal Intake ───────────────────────────────────────────────────────────────


class GoalIntakeResult(BaseModel):
    """Result of AutopilotMonitor.intake_goal (create-first; placement refine is async)."""

    status: Literal["accepted", "rejected", "skipped"]
    goal_id: str | None = None
    reason: str | None = None


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
class WireDependencySuggestion:
    """Suggestion to set hard depends_on edges on a goal (IG-680)."""

    goal_id: str
    depends_on: list[str]


@dataclass
class DagHealthReport:
    """DAG health verification report (LLM and/or structural)."""

    suggest_reset: list[str] = field(default_factory=list)  # Goal IDs to reset
    suggest_remove: list[str] = field(default_factory=list)  # Goal IDs to remove
    suggest_merge: list[MergeSuggestion] = field(default_factory=list)
    suggest_decompose: list[DecomposeSuggestion] = field(default_factory=list)
    suggest_priority_adjust: dict[str, int] = field(default_factory=dict)
    wire_dependencies: list[WireDependencySuggestion] = field(default_factory=list)
    reasoning: str = ""
    errors: list[str] = field(default_factory=list)
