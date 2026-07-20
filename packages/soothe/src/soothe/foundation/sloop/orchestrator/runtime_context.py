"""Mutable runtime bundle for LangGraph Strange Loop nodes (RFC-220)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from soothe.foundation.sloop.engine.anchor_manager import CheckpointAnchorManager
from soothe.foundation.sloop.state.checkpoint import StrangeLoopCheckpoint
from soothe.foundation.sloop.state.execution_checkpoint import GoalIndexEntry
from soothe.foundation.sloop.state.schemas import LoopState
from soothe.foundation.sloop.state.sloop_manager import (
    StrangeLoopStateManager,
)

from .phase_scratch import LoopPhaseScratch

if TYPE_CHECKING:
    from soothe_sdk.protocols.core_agent import CoreAgentProtocol

    from soothe.foundation.autopilot.engine.proposal_queue import ProposalQueue
    from soothe.foundation.sloop.clarification.protocol import ClarificationPolicy
    from soothe.foundation.sloop.engine.strange_loop import StrangeLoop
    from soothe.utils.observability.langfuse import GoalLoopTrace

EmitFn = Callable[[str, Any], Awaitable[None]]

logger = logging.getLogger(__name__)


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
    # state before issuing ``Command(resume=...)``.
    clarification_resume_text: str | None = None
    # RFC-622: per-question answer list. When provided, the orchestrator runner
    # passes the list directly as ``Command(resume={"answers": [...]})`` so the
    # InteractiveClarificationPolicy returns one answer per question rather
    # than broadcasting a single concatenated string. ``None`` falls back to
    # broadcasting ``clarification_resume_text``.
    clarification_resume_answers: list[str] | None = None
    # ProposalQueue for autopilot proposals (report_progress, flag_blocker, etc.)
    proposal_queue: ProposalQueue | None = None
    # RFC-624 Phase 4: ContextEngine is always active
    ce: Any | None = None  # ContextEngine instance
    ce_goal_id: str | None = None  # Active goal ID in CE
    # Shared Langfuse trace for graph entry intent-classify + strange-loop-graph (IG-540).
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
