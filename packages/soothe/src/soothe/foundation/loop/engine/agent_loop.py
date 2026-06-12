"""Main AgentLoop orchestration (RFC-201)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe.config.constants import DEFAULT_AGENT_LOOP_MAX_ITERATIONS
from soothe.foundation.loop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.foundation.loop.planning.phase import PlanPhase
from soothe.foundation.loop.state.manager import AgentLoopStateManager
from soothe.foundation.loop.state.schemas import (
    AgentDecision,
    LoopState,
    PlanResult,
)
from soothe.foundation.loop.state.working_memory import LoopWorkingMemory
from soothe.foundation.loop.utils.reflection import _default_agent_decision
from soothe.protocols.planner import PlanContext, StepResult
from soothe.utils.text_preview import log_preview

from ..orchestrator.nodes.plan_assess import seed_loop_ledger_from_prior_goal
from .anchor_manager import CheckpointAnchorManager

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.config import SootheConfig
    from soothe.foundation.autopilot.engine.proposal_queue import ProposalQueue
    from soothe.foundation.core.agent import CoreAgent
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

        # Eagerly resolve the fast model for scenario classification; None when
        # router.fast is unset (SynthesisGenerator falls back to planner model).
        self._fast_llm: Any | None = None
        if config.router.fast:
            try:
                self._fast_llm = config.create_chat_model("fast")
            except Exception:
                pass

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
        shared_pool: Any | None = None,  # IG-406: SharedPostgreSQLPool for high-concurrency
        clarification_policy: Any | None = None,  # RFC-622: ClarificationPolicy injection
        clarification_answer: bool = False,  # RFC-622: hint that goal is a resume answer
        clarification_answers: list[str] | None = None,  # RFC-622: per-question answer list
        proposal_queue: ProposalQueue | None = None,  # RFC-204 Group C: Layer 2 proposals
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
            intent: IntentClassification (RFC-225). ``quiz`` is short-circuited by the runner;
                ``agentic`` is handled here. Loop continuation is derived from the checkpoint.
            shared_pool: SharedPostgreSQLPool for high-concurrency (IG-406).
                - new_goal: Normal goal execution flow
                - quiz: Should not reach here (handled in runner)
            routing_classification: ``RoutingClassification`` for CoreAgent middleware (IG-383).
            clarification_policy: Optional ``ClarificationPolicy`` (RFC-622) used by
                the loop graph's ``await_clarification`` node. When ``None``, clarification
                requests are deferred via the legacy no-policy path.
            proposal_queue: Optional ``ProposalQueue`` (RFC-204 Group C) for Layer 2
                tools to enqueue goal suggestions and findings during execution.

        Yields:
            Tuples of (event_type, event_data) for progress updates
        """
        from soothe.foundation.workspace.tool_path_resolution import (
            filesystem_virtual_mode_from_soothe_config,
        )
        from soothe.skills.catalog import (
            parse_slash_skill_user_line,
            try_expand_slash_skill_user_line,
        )
        from soothe.skills.workspace_sync import sync_specific_skill_to_workspace

        goal_user_submission: str | None = None
        skill_context: str | None = None
        slash_invoked_skill_name: str | None = None
        slash_invoked_skill_body: str | None = None
        execution_goal = goal

        # Targeted skill sync - only sync the addressed skill
        parsed_skill = parse_slash_skill_user_line(goal)
        if workspace and filesystem_virtual_mode_from_soothe_config(self.config):
            if parsed_skill is not None:
                skill_name = parsed_skill[0]
                sync_specific_skill_to_workspace(self.config, workspace, skill_name)
            # If no skill addressed, skip sync (skills are synced on-demand via middleware)

        skill_env = try_expand_slash_skill_user_line(
            goal,
            self.config,
            workspace=str(workspace) if workspace else None,
        )
        if skill_env is not None:
            goal_user_submission = goal
            skill_context = skill_env.skill_context or None
            # state.goal carries only user instruction; body goes via <SKILL_REFERENCE>
            user_args = parsed_skill[1] if parsed_skill else ""
            execution_goal = (
                user_args.strip()
                if user_args.strip()
                else f"Execute skill: {parsed_skill[0] if parsed_skill else 'unknown'}"
            )
            slash_invoked_skill_name = parsed_skill[0] if parsed_skill else None
            slash_invoked_skill_body = skill_env.skill_context
        elif parsed_skill is not None:
            logger.warning(
                "[AgentLoop] /skill: user line did not expand (missing skill on this host "
                "or unreadable SKILL.md); planner will see the raw line: %s",
                log_preview(goal, 120),
            )

        # Initialize AgentLoop state manager (RFC-205, IG-246: loop_id parameter, IG-055: config)
        # IG-406: Pass shared_pool for high-concurrency support
        state_manager = AgentLoopStateManager(
            loop_id,
            Path(workspace) if workspace else None,
            config=self.config,
            shared_pool=shared_pool,
        )
        # RFC-223: Main AgentLoop thread id must align to loop_id.
        # Keep caller-provided thread_id for upstream intent/routing context, but normalize
        # all AgentLoop checkpoint + execution thread bookkeeping to loop_id.
        main_thread_id = state_manager.loop_id
        if thread_id and thread_id != main_thread_id:
            logger.info(
                "[AgentLoop] normalizing main thread_id to loop_id: input=%s loop_id=%s",
                thread_id,
                main_thread_id,
            )

        # Initialize checkpoint anchor manager for execution synchronization (IG-055: pass config)
        anchor_manager = CheckpointAnchorManager(state_manager.loop_id, config=self.config)

        # RFC-217: Goal context config for CE-backed goal context injection
        from soothe.config.models import GoalContextConfig

        goal_context_config = getattr(self.config.agent.loop, "goal_context", GoalContextConfig())

        # Try to recover from checkpoint (RFC-216: loop-scoped).
        # Use explicit ``loop_id`` from the runner (conversation ``thread_id``) so the
        # same TUI/daemon thread reuses one AgentLoop checkpoint across user turns.
        checkpoint = await state_manager.load()

        if checkpoint is not None:
            checkpoint_normalized = False
            if checkpoint.current_thread_id != main_thread_id:
                checkpoint.current_thread_id = main_thread_id
                checkpoint_normalized = True
            if main_thread_id not in checkpoint.thread_ids:
                checkpoint.thread_ids.append(main_thread_id)
                checkpoint_normalized = True
            if checkpoint_normalized:
                await state_manager.save(checkpoint)
                logger.info(
                    "Normalized checkpoint thread identity to loop_id: loop=%s current_thread_id=%s",
                    state_manager.loop_id,
                    main_thread_id,
                )
        # IG-325: valid resume of a running checkpoint (structural plan-bootstrap guard)
        recovery_valid_resume = False
        goal_record = None
        iteration = 0

        if checkpoint and checkpoint.status == "running":
            current_goal_index = checkpoint.current_goal_index
            if 0 <= current_goal_index < len(checkpoint.goal_history):
                goal_record = checkpoint.goal_history[current_goal_index]
                iteration = goal_record.iteration
                recovery_valid_resume = True
                logger.info(
                    "Recovering from checkpoint at iteration %d (goal: %s)",
                    iteration,
                    goal_record.goal_id,
                )
            elif checkpoint.goal_history and any(
                g.status in ("completed", "failed", "cancelled") for g in checkpoint.goal_history
            ):
                # RFC-225: daemon's pre-query metadata write can clobber `status`
                # from "idle" back to "running" while `current_goal_index` stays
                # at -1 (left by finalize_goal). Goal history still holds prior
                # completed goals — treat as idle continuation: append a new goal,
                # seed from prior, preserve history.
                logger.info(
                    "Checkpoint status=running but current_goal_index=%d with %d prior goal(s); "
                    "treating as idle continuation (loop=%s)",
                    current_goal_index,
                    len(checkpoint.goal_history),
                    state_manager.loop_id,
                )
                # Restore the logical "idle" status before calling start_new_goal
                # (which refuses to start a goal when status=="running").
                checkpoint.status = "idle"
                checkpoint.current_thread_id = main_thread_id
                if main_thread_id not in checkpoint.thread_ids:
                    checkpoint.thread_ids.append(main_thread_id)
                goal_record = state_manager.start_new_goal(execution_goal, max_iterations)
                checkpoint.goal_history.append(goal_record)
                checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
                checkpoint.status = "running"
                if len(checkpoint.goal_history) >= 2:
                    seed_loop_ledger_from_prior_goal(checkpoint, goal_record, main_thread_id)
                await state_manager.save(checkpoint)
                iteration = 0
                recovery_valid_resume = False
            else:
                logger.warning(
                    "Checkpoint has invalid goal index %d (history length: %d), re-initializing",
                    current_goal_index,
                    len(checkpoint.goal_history),
                )
                checkpoint = await state_manager.initialize(main_thread_id, max_iterations)
                goal_record = state_manager.start_new_goal(execution_goal, max_iterations)
                checkpoint.goal_history.append(goal_record)
                checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
                checkpoint.status = "running"
                await state_manager.save(checkpoint)
                iteration = 0
                recovery_valid_resume = False

        elif checkpoint and checkpoint.status == "idle":
            checkpoint.current_thread_id = main_thread_id
            if main_thread_id not in checkpoint.thread_ids:
                checkpoint.thread_ids.append(main_thread_id)
            goal_record = state_manager.start_new_goal(execution_goal, max_iterations)
            checkpoint.goal_history.append(goal_record)
            checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
            checkpoint.status = "running"
            # RFC-225: always seed prior goal context for same-loop goals.
            # A new goal within an existing loop benefits from prior context
            # (e.g., "DUMP review to report" needs the review's findings).
            if len(checkpoint.goal_history) >= 2:
                seed_loop_ledger_from_prior_goal(checkpoint, goal_record, main_thread_id)
            await state_manager.save(checkpoint)
            iteration = 0
            logger.debug(
                "continued loop %s: new goal id=%s idx=%d",
                state_manager.loop_id,
                goal_record.goal_id,
                checkpoint.current_goal_index,
            )

        else:
            if checkpoint is not None:
                logger.info(
                    "Starting fresh AgentLoop checkpoint (prior status=%s loop_id=%s)",
                    checkpoint.status,
                    state_manager.loop_id,
                )
            checkpoint = await state_manager.initialize(main_thread_id, max_iterations)
            goal_record = state_manager.start_new_goal(execution_goal, max_iterations)
            checkpoint.goal_history.append(goal_record)
            checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
            checkpoint.status = "running"

            logger.debug(
                "created goal: id=%s idx=%d obj=%d",
                goal_record.goal_id,
                checkpoint.current_goal_index,
                id(goal_record),
            )

            await state_manager.save(checkpoint)

        # RFC-225: derive continue_loop_mode from the FINAL checkpoint state, AFTER
        # branching has settled goal_history. True iff at least one prior goal exists
        # alongside the active one (i.e., goal_history has 2+ entries). The valid-resume
        # branch keeps goal_history unchanged, so this also covers resumes where the
        # in-flight goal is not the first goal of the loop.
        continue_loop_mode = len(checkpoint.goal_history) >= 2 or (
            recovery_valid_resume and len(checkpoint.goal_history) >= 2
        )

        state = LoopState(
            goal=execution_goal,
            goal_user_submission=goal_user_submission,
            skill_context=skill_context,
            slash_invoked_skill_name=slash_invoked_skill_name,
            slash_invoked_skill_body=slash_invoked_skill_body,
            thread_id=main_thread_id,
            workspace=workspace,
            git_status=git_status,
            iteration=iteration,  # Use recovered or initial iteration
            max_iterations=max_iterations,
            intent=intent,
            routing_classification=routing_classification,
            loop_messages=goal_record.loop_messages if goal_record else [],
        )

        # RFC-225: propagate continue_loop_mode onto LoopState for executor wiring
        state.continue_loop = continue_loop_mode

        wm_cfg = self.config.agent.loop.working_memory
        if wm_cfg.enabled:
            state.working_memory = LoopWorkingMemory(
                thread_id=main_thread_id,
                max_inline_chars=wm_cfg.max_inline_chars,
                max_entry_chars_before_spill=wm_cfg.max_entry_chars_before_spill,
            )

        logger.info(
            "[Goal] %s (max_iterations=%d, iteration=%d, continue_loop=%s)",
            log_preview(execution_goal, 80),
            max_iterations,
            state.iteration,
            continue_loop_mode,
        )

        queue: asyncio.Queue[Any] = asyncio.Queue()
        _graph_sentinel = object()

        async def emit(event_type: str, event_data: Any) -> None:
            await queue.put((event_type, event_data))

        plan_manager: Any

        # RFC-624 Phase 4: ContextEngine is always active
        from soothe.context.engine import ContextEngine as _ContextEngine
        from soothe.context.persistence.in_memory import InMemoryContextPersistence
        from soothe.context.planning import StepPlanManagerAdapter

        from .context_adapters import (
            ContextEngineGoalContextAdapter,
        )

        ce_config = self.config.agent.loop.context_engine

        persistence = InMemoryContextPersistence()
        if ce_config.persistence_backend == "file":
            from pathlib import Path as _Path

            from soothe.context.persistence.file_backend import FileContextPersistence

            soothe_home = (
                _Path(self.config.home)
                if hasattr(self.config, "home")
                else _Path.home() / ".soothe"
            )
            persistence = FileContextPersistence(
                loop_id=state_manager.loop_id,
                soothe_home=soothe_home,
            )

        ce_instance = _ContextEngine(
            persistence=persistence,
            soothe_home=Path(self.config.home) if hasattr(self.config, "home") else None,
            workspace=Path(workspace) if workspace else None,
        )
        ce_goal = await ce_instance.create_goal(
            execution_goal,
            generating_reasoning="AgentLoop goal",
            source="user",
        )
        await ce_instance.activate_goal(ce_goal.id, loop_id=state_manager.loop_id)

        # Load semantic context at goal start
        try:
            if workspace:
                ce_instance._semantic.workspace = Path(workspace)
                ce_instance._semantic.load_project_instructions()
                ce_instance._semantic.load_agent_instructions()
                ce_instance._semantic.load_memory()
        except Exception:
            logger.warning("[CE] on_goal_start semantic loading failed", exc_info=True)

        plan_manager = StepPlanManagerAdapter(
            subengine=ce_instance.planning.step,
            goal_id=ce_goal.id,
        )

        # Replace GoalContextManager with CE-backed adapter
        goal_context_manager = ContextEngineGoalContextAdapter(
            context_engine=ce_instance,
            state_manager=state_manager,
            config=goal_context_config,
        )

        logger.info(
            "ContextEngine active (goal_id=%s, backend=%s)",
            ce_goal.id,
            ce_config.persistence_backend,
        )

        ctx = LoopRuntimeContext(
            agent_loop=self,
            state_manager=state_manager,
            anchor_manager=anchor_manager,
            goal_context_manager=goal_context_manager,
            plan_manager=plan_manager,
            checkpoint=checkpoint,
            goal_record=goal_record,
            continue_loop_mode=continue_loop_mode,
            recovery_valid_resume=recovery_valid_resume,
            loop_state=state,
            emit=emit,
            intent_classifier=intent_classifier,
            preferred_subagent=preferred_subagent,
            clarification_policy=clarification_policy,
            clarification_resume_text=goal if clarification_answer else None,
            clarification_resume_answers=(
                list(clarification_answers)
                if clarification_answer and clarification_answers
                else None
            ),
            proposal_queue=proposal_queue,  # RFC-204 Group C
            ce=ce_instance,
            ce_goal_id=ce_goal.id,
        )

        async def pump_graph() -> None:
            try:
                from soothe.foundation.loop.orchestrator.runner import invoke_agent_loop_graph

                await invoke_agent_loop_graph(ctx)
            except Exception as e:
                logger.error(
                    "[pump_graph] Graph execution error: %s: %s",
                    type(e).__name__,
                    e,
                    exc_info=True,
                )
                raise
            finally:
                await queue.put(_graph_sentinel)

        pump_task = asyncio.create_task(pump_graph())
        try:
            while True:
                item = await queue.get()
                if item is _graph_sentinel:
                    logger.debug(
                        "[run_with_progress] Graph sentinel received, ending stream (loop=%s)",
                        ctx.state_manager.loop_id,
                    )
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
            # IG-404: Close backend pools to prevent connection exhaustion
            await state_manager.close()
            await anchor_manager.close()

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
