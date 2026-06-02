"""Mutable runtime bundle for LangGraph Agent Loop nodes (RFC-220)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from soothe.core.loop.engine.anchor_manager import CheckpointAnchorManager
from soothe.core.loop.engine.goal_context_manager import GoalContextManager
from soothe.core.loop.planning.manager import PlanManager
from soothe.core.loop.state.checkpoint import AgentLoopCheckpoint, GoalExecutionRecord
from soothe.core.loop.state.manager import AgentLoopStateManager
from soothe.core.loop.state.schemas import LoopState

from .phase_scratch import LoopPhaseScratch

if TYPE_CHECKING:
    from soothe.core.agent import CoreAgent
    from soothe.core.loop.clarification.protocol import ClarificationPolicy
    from soothe.core.loop.engine.agent_loop import AgentLoop

EmitFn = Callable[[str, Any], Awaitable[None]]

logger = logging.getLogger(__name__)


@dataclass
class LoopRuntimeContext:
    """Shared handles for one goal run; not serialized by LangGraph."""

    agent_loop: AgentLoop
    state_manager: AgentLoopStateManager
    anchor_manager: CheckpointAnchorManager
    goal_context_manager: GoalContextManager
    plan_manager: PlanManager
    checkpoint: AgentLoopCheckpoint
    goal_record: GoalExecutionRecord | None
    continue_loop_mode: bool
    recovery_valid_resume: bool
    loop_state: LoopState
    emit: EmitFn
    intent_classifier: Any | None = None
    preferred_subagent: str | None = None
    scratch: LoopPhaseScratch = field(default_factory=LoopPhaseScratch)
    clarification_policy: ClarificationPolicy | None = None

    @property
    def core_agent(self) -> CoreAgent:
        """Layer 1 graph (checkpoint key = ``thread_id``, not loop_id)."""
        return self.agent_loop.core_agent

    async def mark_goal_status(self, status: str, reason: str = "") -> None:
        """Update the running goal's status (best-effort).

        Solo loop: logs only — the loop simply terminates with ``deferred``
        outcome and the operator restarts when ready.
        Autopilot: a goal-engine-aware subclass is expected to override this
        and notify the scheduler that the goal is blocked.
        """
        logger.info("[ClarificationRelay] goal status -> %s (reason=%s)", status, reason)
