"""Per-iteration planner scratch shared across Loop Graph nodes (RFC-220).

LangGraph node ``state`` carries routing keys; phase payloads live here on ``LoopRuntimeContext``
because they reference rich non-primitive models (not serialized in graph checkpoints today).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from soothe.foundation.loop.state.schemas import (
    AgentDecision,
    PlanResult,
    StatusAssessment,
)


@dataclass
class LoopPhaseScratch:
    """Mutable planner outputs for one iteration cycle."""

    plan_result: PlanResult | None = None
    plan_assessment: StatusAssessment | None = None
    decision: AgentDecision | None = None
    iteration_perf_start: float | None = None
    step_results: list[Any] = field(default_factory=list)
