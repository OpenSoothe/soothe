"""Mutable runtime bundle for LangGraph Agent Loop nodes (RFC-220)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from soothe.core.agent_loop.branching.anchor_manager import CheckpointAnchorManager
from soothe.core.agent_loop.context.goal_context_manager import GoalContextManager
from soothe.core.agent_loop.planning.manager import PlanManager
from soothe.core.agent_loop.state.checkpoint import AgentLoopCheckpoint, GoalExecutionRecord
from soothe.core.agent_loop.state.manager import AgentLoopStateManager
from soothe.core.agent_loop.state.schemas import LoopState

from .phase_scratch import LoopPhaseScratch

if TYPE_CHECKING:
    from soothe.core.agent import CoreAgent
    from soothe.core.agent_loop.engine.agent_loop import AgentLoop

EmitFn = Callable[[str, Any], Awaitable[None]]


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
    thread_continuation_mode: bool
    recovery_valid_resume: bool
    loop_state: LoopState
    emit: EmitFn
    intent_classifier: Any | None = None
    preferred_subagent: str | None = None
    recent_messages_for_intent: list[Any] | None = None
    active_goal_id_for_intent: str | None = None
    active_goal_description_for_intent: str | None = None
    scratch: LoopPhaseScratch = field(default_factory=LoopPhaseScratch)

    @property
    def core_agent(self) -> CoreAgent:
        """Layer 1 graph (checkpoint key = ``thread_id``, not loop_id)."""
        return self.agent_loop.core_agent
