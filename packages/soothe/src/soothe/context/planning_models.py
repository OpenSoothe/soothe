"""Planning-specific models for the Context Engine planning submodule (RFC-624 Phase 3c)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class PlanWave(BaseModel):
    """Record of a single plan ingestion wave."""

    plan_id: str | None = None
    iteration: int = 0
    step_count: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SubGoalSpec(BaseModel):
    """Specification for a subgoal to be created during decomposition."""

    description: str
    priority: int = 50
    depends_on: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    informs: list[str] = Field(default_factory=list)


class DecompositionResult(BaseModel):
    """Result of goal decomposition."""

    subgoals: list[SubGoalSpec] = Field(default_factory=list)
    reasoning: str = ""
    strategy: Literal["sequential", "parallel", "mixed"] = "parallel"


class CompletionStrategy(StrEnum):
    """Strategy for producing the final goal response."""

    LEDGER_DIRECT = "ledger_direct"
    SYNTHESIZE = "synthesize"


@dataclass
class DagPlanningContext:
    """Structured DAG summary for LLM planning (IG-400 interleaving).

    Shared between PlanManager and StepPlanningSubengine. Lives here
    to avoid circular imports between manager.py and step_planner.py.
    """

    pending_step_ids: set[str] = field(default_factory=set)
    failed_step_ids: set[str] = field(default_factory=set)
    ready_step_ids: set[str] = field(default_factory=set)
    chain_depth: int = 0
    success_rate: float = 1.0
    replan_count: int = 0
    total_steps: int = 0
    completed_steps: int = 0

    @property
    def has_prior_state(self) -> bool:
        return self.total_steps > 0
