"""Per-iteration planner scratch shared across Loop Graph nodes (RFC-220).

LangGraph node ``state`` carries routing keys; phase payloads live here on ``LoopRuntimeContext``
because they reference rich non-primitive models (not serialized in graph checkpoints today).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from soothe.sloop.state.schemas import (
    AgentDecision,
    PlanGapAnalysis,
    PlanResult,
    StatusAssessment,
)


@dataclass
class LoopPhaseScratch:
    """Mutable planner outputs for one iteration cycle."""

    plan_result: PlanResult | None = None
    plan_assessment: StatusAssessment | None = None
    plan_gap: PlanGapAnalysis | None = None
    decision: AgentDecision | None = None
    undersized_plan_replan_attempts: int = 0
    iteration_perf_start: float | None = None
    step_results: list[Any] = field(default_factory=list)
    # RFC-633 / IG-658: intake planner *subagent* review gate (not StrangeLoop plan_*)
    plan_artifact_path: str | None = None
    plan_artifact_markdown: str | None = None
    planner_subagent_review_comments: str | None = None
    # IG-660: Approve → StrangeLoop plan_generate handoff (one-shot).
    planner_implement_handoff: bool = False
