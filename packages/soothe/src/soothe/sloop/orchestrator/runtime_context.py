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

EmitFn = Callable[[str, Any], Awaitable[None]]

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
    # RFC-633 / intake planner *subagent* review gate (not StrangeLoop plan_*)
    plan_artifact_path: str | None = None
    plan_artifact_markdown: str | None = None
    planner_subagent_review_comments: str | None = None
    # Approve → StrangeLoop plan_generate handoff (one-shot).
    planner_implement_handoff: bool = False


@dataclass
class LoopRuntimeContext:
    """Shared handles for one goal run; not serialized by LangGraph."""

    strange_loop: StrangeLoop  # Primary field - must be first and required
    state_manager: StrangeLoopStateManager
    anchor_manager: CheckpointAnchorManager
    goal_context_manager: Any  # GoalContextManager or ContextEngineGoalContextAdapter (duck-typed)
    plan_manager: Any  # StepPlanManagerAdapter (duck-typed, 5-method contract)
    checkpoint: StrangeLoopCheckpoint
    goal_record: GoalIndexEntry | None
    continue_loop_mode: bool
    recovery_valid_resume: bool
    loop_state: LoopState
    emit: EmitFn
    intent_classifier: Any | None = None
    preferred_subagent: str | None = None
    scratch: LoopPhaseScratch = field(default_factory=LoopPhaseScratch)
    clarification_policy: ClarificationPolicy | None = None
    # RFC-622: when set, the next graph invocation should resume a pending
    # ``await_clarification`` interrupt with this answer instead of starting a
    # new iteration. Verified against ``pending_clarification`` in the graph
    # state before issuing ``Command(resume=...)``. Cleared by
    # ``await_clarification`` after a successful answer so a later park in the
    # same invocation re-emits ``clarification_requested``.
    clarification_resume_text: str | None = None
    # RFC-622: per-question answer list. When provided, the orchestrator runner
    # passes the list directly as ``Command(resume={"answers": [...]})`` so the
    # InteractiveClarificationPolicy returns one answer per question rather
    # than broadcasting a single concatenated string. ``None`` falls back to
    # broadcasting ``clarification_resume_text``. Cleared with
    # ``clarification_resume_text`` after successful consume.
    clarification_resume_answers: list[str] | None = None
    # RFC-624 Phase 4: ContextEngine is always active
    ce: Any | None = None  # ContextEngine instance
    ce_goal_id: str | None = None  # Active goal ID in CE
    # Shared Langfuse trace for graph entry intake + strange-loop-graph.
    goal_trace: GoalLoopTrace | None = None
    # Background checkpoint finalize started at goal completion; drained before close().
    tail_persistence_task: asyncio.Task[None] | None = None

    @property
    def core_agent(self) -> CoreAgentProtocol:
        """Layer 1 graph (checkpoint key = ``thread_id``, not loop_id)."""
        return self.strange_loop.core_agent

    async def mark_goal_status(self, status: str, reason: str = "") -> None:
        """Update the running goal's status (best-effort).

        Solo loop: logs only — the loop simply terminates with ``deferred``
        outcome and the operator restarts when ready.
        Autopilot: a goal-engine-aware subclass is expected to override this
        and notify the scheduler that the goal is blocked.
        """
        logger.info("[ClarificationRelay] goal status -> %s (reason=%s)", status, reason)
