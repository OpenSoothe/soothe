"""Main AgentLoop orchestration (RFC-201)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe.config.constants import DEFAULT_AGENT_LOOP_MAX_ITERATIONS
from soothe.core.agent_loop.branching.anchor_manager import CheckpointAnchorManager
from soothe.core.agent_loop.context.goal_context_manager import GoalContextManager
from soothe.core.agent_loop.core.plan_manager import PlanManager
from soothe.core.agent_loop.core.plan_phase import PlanPhase
from soothe.core.agent_loop.graph.runtime_context import LoopRuntimeContext
from soothe.core.agent_loop.state.schemas import (
    AgentDecision,
    LoopState,
    PlanResult,
)
from soothe.core.agent_loop.state.state_manager import AgentLoopStateManager
from soothe.core.agent_loop.state.working_memory import LoopWorkingMemory
from soothe.core.agent_loop.utils.reflection import _default_agent_decision
from soothe.protocols.planner import PlanContext, StepResult
from soothe.utils.text_preview import log_preview

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.config import SootheConfig
    from soothe.core.agent import CoreAgent
    from soothe.protocols.loop_planner import LoopPlannerProtocol

logger = logging.getLogger(__name__)


class AgentLoop:
    """Agentic goal execution using Plan-and-Execute pattern (RFC-220 Loop Graph).

    Orchestration is a compiled LangGraph whose configurable checkpoint key is ``loop_id``.
    Plan combines assessment and planning; Execute runs steps via CoreAgent (``thread_id``).

    Attributes:
        core_agent: Layer 1 CoreAgent for step execution
        loop_planner: Plan phase (RFC-604: assessment + conditional plan generation per iteration)
        config: Soothe configuration
    """

    def __init__(
        self,
        core_agent: CoreAgent,
        loop_planner: LoopPlannerProtocol,
        config: SootheConfig,
    ) -> None:
        """Initialize AgentLoop.

        Args:
            core_agent: Layer 1 CoreAgent runtime
            loop_planner: Plan-phase implementation (planning + assessment)
            config: Soothe configuration
        """
        self.core_agent = core_agent
        self.loop_planner = loop_planner
        self.config = config

        self.plan_phase = PlanPhase(loop_planner)

    async def run(
        self,
        goal: str,
        thread_id: str,
        max_iterations: int = DEFAULT_AGENT_LOOP_MAX_ITERATIONS,
    ) -> PlanResult:
        """Run Plan → Execute loop for goal execution.

        Args:
            goal: Goal description to execute
            thread_id: Thread context for execution
            max_iterations: Maximum loop iterations (default: 8)

        Returns:
            PlanResult with final status and evidence
        """
        final_result = None
        async for event_type, event_data in self.run_with_progress(
            goal, thread_id, max_iterations=max_iterations
        ):
            if event_type == "completed":
                final_result = event_data["result"] if isinstance(event_data, dict) else event_data
        return final_result or PlanResult(
            status="replan",
            plan_action="new",
            decision=_default_agent_decision(goal),
            evidence_summary="",
            goal_progress="none",  # IG-399
            next_action="I need to stop here before completion.",
        )

    async def run_with_progress(
        self,
        goal: str,
        thread_id: str,
        workspace: str | None = None,
        git_status: dict[str, Any] | None = None,
        max_iterations: int = DEFAULT_AGENT_LOOP_MAX_ITERATIONS,
        loop_id: str | None = None,  # IG-246: explicit loop_id parameter
        intent: Any | None = None,  # Intent classification
        routing_classification: Any | None = None,  # IG-349, IG-383: RoutingClassification
        intent_classifier: Any | None = None,
        preferred_subagent: str | None = None,
        recent_messages_for_intent: list[Any] | None = None,
        active_goal_id_for_intent: str | None = None,
        active_goal_description_for_intent: str | None = None,
    ) -> AsyncGenerator[tuple[str, Any], None]:
        """Run loop with progress events (RFC-0020 compliant).

        Yields progress events during execution for display.

        Args:
            goal: Goal description to execute
            thread_id: Thread context for execution
            workspace: Thread-specific workspace path (RFC-103)
            git_status: Optional git snapshot for RFC-104-aligned Reason prompts.
            max_iterations: Maximum loop iterations (default: 8)
            loop_id: Optional loop_id (None → auto-generate UUID)
            intent: IntentClassification from unified classifier (IG-226). Determines goal handling:
                - thread_continuation: Adjust iteration behavior, reuse working memory
                - new_goal: Normal goal execution flow
                - chitchat: Should not reach here (handled in runner)
            routing_classification: ``RoutingClassification`` for CoreAgent middleware (IG-383).

        Yields:
            Tuples of (event_type, event_data) for progress updates
        """
        # Initialize AgentLoop state manager (RFC-205, IG-246: loop_id parameter, IG-055: config)
        state_manager = AgentLoopStateManager(
            loop_id, Path(workspace) if workspace else None, config=self.config
        )

        # Initialize checkpoint anchor manager for execution synchronization (IG-055: pass config)
        anchor_manager = CheckpointAnchorManager(state_manager.loop_id, config=self.config)

        # IG-226: Handle thread continuation intent
        thread_continuation_mode = False
        if intent and hasattr(intent, "intent_type"):
            if intent.intent_type == "thread_continuation":
                thread_continuation_mode = True
                logger.info(
                    "[AgentLoop] Thread continuation mode: reuse_current_goal=%s",
                    intent.reuse_current_goal if hasattr(intent, "reuse_current_goal") else False,
                )
                # Thread continuation may benefit from fewer iterations (follow-up actions)
                # but keep max_iterations unchanged for now - let Plan phase determine completion

        # RFC-217: Create GoalContextManager for goal-level context injection
        from soothe.config.models import GoalContextConfig

        goal_context_config = getattr(self.config.agentic, "goal_context", GoalContextConfig())
        goal_context_manager = GoalContextManager(state_manager, goal_context_config)

        # Try to recover from checkpoint (RFC-216: loop-scoped)
        checkpoint = await state_manager.load()
        # IG-325: valid resume of a running checkpoint (structural plan-bootstrap guard)
        recovery_valid_resume = False
        if checkpoint and checkpoint.status == "running":
            # Get current goal iteration (RFC-216: per-goal tracking)
            current_goal_index = checkpoint.current_goal_index
            if current_goal_index >= 0 and current_goal_index < len(checkpoint.goal_history):
                goal_record = checkpoint.goal_history[current_goal_index]
                iteration = goal_record.iteration
                recovery_valid_resume = True
                logger.info(
                    "Recovering from checkpoint at iteration %d (goal: %s)",
                    iteration,
                    goal_record.goal_id,
                )
            else:
                # No active goal in recovered checkpoint - invalid state
                # Treat as new checkpoint instead of failing
                logger.warning(
                    "Checkpoint has invalid goal index %d (history length: %d), initializing fresh state",
                    current_goal_index,
                    len(checkpoint.goal_history),
                )
                checkpoint = await state_manager.initialize(thread_id, max_iterations)
                iteration = 0
                goal_record = None
                recovery_valid_resume = False

            # RFC-214: Ledger is already populated in goal_record.loop_messages
            # No need to derive plan conversation separately
        else:
            # Initialize new checkpoint (RFC-216: pass thread_id, not goal)
            checkpoint = await state_manager.initialize(thread_id, max_iterations)
            iteration = 0  # New goal starts at iteration 0
            # Create new goal_record for this goal execution
            goal_record = state_manager.start_new_goal(goal, max_iterations)
            checkpoint.goal_history.append(goal_record)  # Append FIRST
            checkpoint.current_goal_index = len(checkpoint.goal_history) - 1  # Compute index AFTER
            checkpoint.status = "running"

            logger.debug(
                "created goal: id=%s idx=%d obj=%d",
                goal_record.goal_id,
                checkpoint.current_goal_index,
                id(goal_record),
            )

            await state_manager.save(checkpoint)

        state = LoopState(
            goal=goal,
            thread_id=thread_id,
            workspace=workspace,
            git_status=git_status,
            iteration=iteration,  # Use recovered or initial iteration
            max_iterations=max_iterations,
            intent=intent,
            routing_classification=routing_classification,
            loop_messages=goal_record.loop_messages if goal_record else [],
        )

        # IG-226: Set thread continuation flag for working memory context
        if thread_continuation_mode:
            state.thread_continuation = True  # Add flag to LoopState if it exists
            logger.debug("[AgentLoop] Thread continuation flag set for working memory enhancement")

        wm_cfg = self.config.agentic.working_memory
        if wm_cfg.enabled:
            state.working_memory = LoopWorkingMemory(
                thread_id=thread_id,
                max_inline_chars=wm_cfg.max_inline_chars,
                max_entry_chars_before_spill=wm_cfg.max_entry_chars_before_spill,
            )

            # IG-226: Thread continuation working memory enhancement
            # Reuse current thread's working memory content more aggressively
            if thread_continuation_mode:
                logger.info("[AgentLoop] Thread continuation: working memory context reuse enabled")
                # Working memory will automatically load from thread persistence
                # No special handling needed - it already loads existing entries

        logger.info(
            "[Goal] %s (max_iterations=%d, iteration=%d, thread_continuation=%s)",
            log_preview(goal, 80),
            max_iterations,
            state.iteration,
            thread_continuation_mode,
        )

        queue: asyncio.Queue[Any] = asyncio.Queue()
        _graph_sentinel = object()

        async def emit(event_type: str, event_data: Any) -> None:
            await queue.put((event_type, event_data))

        plan_manager = PlanManager(goal=goal)

        ctx = LoopRuntimeContext(
            agent_loop=self,
            state_manager=state_manager,
            anchor_manager=anchor_manager,
            goal_context_manager=goal_context_manager,
            plan_manager=plan_manager,
            checkpoint=checkpoint,
            goal_record=goal_record,
            thread_continuation_mode=thread_continuation_mode,
            recovery_valid_resume=recovery_valid_resume,
            loop_state=state,
            emit=emit,
            intent_classifier=intent_classifier,
            preferred_subagent=preferred_subagent,
            recent_messages_for_intent=recent_messages_for_intent,
            active_goal_id_for_intent=active_goal_id_for_intent,
            active_goal_description_for_intent=active_goal_description_for_intent,
        )

        async def pump_graph() -> None:
            try:
                from soothe.core.agent_loop.graph.runner import invoke_agent_loop_graph

                await invoke_agent_loop_graph(ctx)
            finally:
                await queue.put(_graph_sentinel)

        pump_task = asyncio.create_task(pump_graph())
        try:
            while True:
                item = await queue.get()
                if item is _graph_sentinel:
                    break
                yield item
        except asyncio.CancelledError:
            pump_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump_task
            raise
        finally:
            if not pump_task.done():
                pump_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pump_task
            else:
                await pump_task

    def _resolve_decision(
        self,
        plan_result: PlanResult,
        state: LoopState,
    ) -> AgentDecision | None:
        """Pick the AgentDecision to execute for this Execute phase."""
        if plan_result.plan_action == "keep":
            if state.current_decision is None:
                logger.warning(
                    "[Plan] plan_action=keep but no current_decision; falling back to new decision"
                )
                return plan_result.decision
            return state.current_decision
        return plan_result.decision

    def _build_plan_context(self, state: LoopState) -> PlanContext:
        """Build planning context with available capabilities and completed steps.

        Args:
            state: Current loop state with step results

        Returns:
            PlanContext with tools, subagents, and completed steps for the reasoner
        """
        available_tools = []
        if hasattr(self.core_agent, "tools") and isinstance(self.core_agent.tools, dict):
            available_tools = list(self.core_agent.tools.keys())

        available_subagents = [name for name, cfg in self.config.subagents.items() if cfg.enabled]

        completed_steps = [
            StepResult(
                step_id=r.step_id,
                outcome=r.outcome if r.success else {"type": "error", "error": r.error or ""},
                success=r.success,
                duration_ms=r.duration_ms,
            )
            for r in state.step_results
        ]

        return PlanContext(
            available_capabilities=available_tools + available_subagents,
            recent_messages=[],  # RFC-214: Now using loop_messages ledger directly
            completed_steps=completed_steps,
            routing_classification=getattr(state, "routing_classification", None),
            workspace=state.workspace,
            git_status=state.git_status,
            thread_id=state.thread_id,
        )
