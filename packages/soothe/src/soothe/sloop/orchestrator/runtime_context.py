"""Mutable runtime bundle for LangGraph Strange Loop nodes (RFC-220).

Per-iteration planner scratch lives on ``LoopRuntimeContext`` (not graph
channels) because payloads reference rich non-primitive models that are not
serialized in LangGraph checkpoints today.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from soothe.sloop.engine.anchor_manager import CheckpointAnchorManager
from soothe.sloop.state.checkpoint import StrangeLoopCheckpoint
from soothe.sloop.state.execution_checkpoint import GoalIndexEntry
from soothe.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    PlanGapAnalysis,
    PlanResult,
    StatusAssessment,
)
from soothe.sloop.state.sloop_manager import (
    StrangeLoopStateManager,
)

if TYPE_CHECKING:
    from soothe_sdk.protocols.core_agent import CoreAgentProtocol

    from soothe.sloop.clarification.protocol import ClarificationPolicy
    from soothe.sloop.engine.strange_loop import StrangeLoop
    from soothe.utils.observability.langfuse import GoalLoopTrace

logger = logging.getLogger(__name__)


@dataclass
class LoopPhaseScratch:
    """Mutable planner outputs for one iteration cycle."""

    plan_result: PlanResult | None = None
    plan_assessment: StatusAssessment | None = None
    plan_gap: PlanGapAnalysis | None = None
    decision: AgentDecision | None = None
    iteration_perf_start: float | None = None
    step_results: list[Any] = field(default_factory=list)
    # Planner-subagent review gate (not StrangeLoop plan_*).
    plan_artifact_path: str | None = None
    plan_artifact_markdown: str | None = None
    planner_subagent_review_comments: str | None = None
    # Approve → StrangeLoop plan_generate handoff (one-shot).
    planner_implement_handoff: bool = False


@dataclass
class LoopRuntimeContext:
    """Shared handles for one goal run; not serialized by LangGraph."""

    strange_loop: StrangeLoop
    state_manager: StrangeLoopStateManager
    anchor_manager: CheckpointAnchorManager
    goal_context_manager: Any  # GoalContextManager or CE adapter (duck-typed)
    plan_manager: Any  # StepPlanManagerAdapter (duck-typed)
    checkpoint: StrangeLoopCheckpoint
    goal_record: GoalIndexEntry | None
    continue_loop_mode: bool
    recovery_valid_resume: bool
    loop_state: LoopState
    emit: Callable[[str, Any], Awaitable[None]]
    intent_classifier: Any | None = None
    preferred_subagent: str | None = None
    scratch: LoopPhaseScratch = field(default_factory=LoopPhaseScratch)
    clarification_policy: ClarificationPolicy | None = None
    # Next invoke resumes await_user via Command(resume=...); cleared after consume.
    clarification_resume_text: str | None = None
    clarification_resume_answers: list[str] | None = None
    ce: Any | None = None
    ce_goal_id: str | None = None
    goal_trace: GoalLoopTrace | None = None
    tail_persistence_task: asyncio.Task[None] | None = None

    @property
    def core_agent(self) -> CoreAgentProtocol:
        """CoreAgent graph (checkpoint key = ``thread_id``, not loop_id)."""
        return self.strange_loop.core_agent

    async def mark_goal_status(self, status: str, reason: str = "") -> None:
        """Update the running goal's status (best-effort).

        Solo loop: logs only. Autopilot subclasses should notify the scheduler.
        """
        logger.info("[ClarificationRelay] goal status -> %s (reason=%s)", status, reason)
