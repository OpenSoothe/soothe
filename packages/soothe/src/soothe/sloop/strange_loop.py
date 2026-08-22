"""Main StrangeLoop orchestration (RFC-201)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from soothe_nano.utils.text_preview import log_preview
from soothe_sdk.protocols.planner import PlanContext
from soothe_sdk.protocols.planner import StepResult as SdkStepResult

from soothe.config.constants import DEFAULT_STRANGE_LOOP_MAX_ITERATIONS
from soothe.sloop.intention.models import (
    build_loop_routing_classification,
    normalize_response_language,
)
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    PlanResult,
)
from soothe.sloop.state.sloop_manager import StrangeLoopStateManager
from soothe.sloop.state.working_memory import LoopWorkingMemory
from soothe.sloop.utils.continue_keyword import (
    is_continue_keyword,
    is_interrupt_resume_keyword,
)
from soothe.sloop.utils.reflection import _default_agent_decision
from soothe.sloop.utils.structural_continuation import (
    has_resumable_interrupted_goal,
    is_loop_control_signal,
)
from soothe.utils.observability.langfuse import SootheLangfuse

from .checkpoints.anchor_manager import CheckpointAnchorManager

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe_sdk.protocols.core_agent import CoreAgentProtocol

    from soothe.config import SootheConfig


def _hydrate_previous_plan_from_ce(state: LoopState, ce_goal: Any) -> None:
    """Restore ``LoopState.previous_plan`` from a reused CE goal when present.

    Without this, interrupt resume plans as if no prior wave existed even though
    the CE step DAG still holds completed steps.
    """
    raw = getattr(ce_goal, "previous_plan", None)
    if not raw or state.previous_plan is not None:
        return
    try:
        if isinstance(raw, PlanResult):
            state.previous_plan = raw
        elif isinstance(raw, dict):
            state.previous_plan = PlanResult.model_validate(raw)
    except Exception:
        logger.debug(
            "[Goal] previous_plan hydrate failed for CE goal %s",
            getattr(ce_goal, "id", None),
            exc_info=True,
        )


class StrangeLoop:
    """Agentic goal execution via the RFC-904 DISPATCH / THREAD graph.

    Orchestration is a compiled LangGraph whose configurable checkpoint key is ``loop_id``.
    Execute runs claimed CE steps via CoreAgent (``thread_id``).

    Attributes:
        core_agent: CoreAgent for step execution
        config: Soothe configuration
    """

    def __init__(
        self,
        core_agent: CoreAgentProtocol,
        config: SootheConfig,
    ) -> None:
        """Initialize StrangeLoop.

        Args:
            core_agent: CoreAgent runtime
            config: Soothe configuration
        """
        self.core_agent = core_agent
        self.config = config

        # RFC-624 Phase 4: Loop-scoped CE instance (created on first run_with_progress)
        self._ce: Any | None = None

        # Eagerly resolve the fast model for scenario classification / step briefs.
        self._fast_llm: Any | None = None
        if config.router.fast:
            try:
                self._fast_llm = config.create_chat_model("fast")
            except Exception:
                pass

        self._goal_synthesis_llm: Any | None = None
        try:
            self._goal_synthesis_llm = config.create_chat_model(
                config.agent.loop.goal_synthesis_model_role
            )
        except Exception:
            self._goal_synthesis_llm = self._fast_llm

    def goal_synthesis_model(self) -> Any:
        """Resolved chat model for goal-completion synthesis."""
        if self._goal_synthesis_llm is not None:
            return self._goal_synthesis_llm
        return self._fast_llm

    async def run(
        self,
        goal: str,
        thread_id: str,
        max_iterations: int = DEFAULT_STRANGE_LOOP_MAX_ITERATIONS,
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
            goal_progress="none",  #
            next_action="I need to stop here before completion.",
        )

    async def run_with_progress(
        self,
        goal: str,
        thread_id: str,
        workspace: str | None = None,
        max_iterations: int = DEFAULT_STRANGE_LOOP_MAX_ITERATIONS,
        loop_id: str | None = None,  # explicit loop_id parameter
        intent: Any | None = None,  # Intent classification
        routing_classification: Any | None = None,  # , RoutingClassification
        intent_classifier: Any | None = None,
        preferred_subagent: str | None = None,
        shared_pool: Any | None = None,  # SharedPostgreSQLPool for high-concurrency
        clarification_policy: Any | None = None,  # RFC-622: ClarificationPolicy injection
        clarification_answer: bool = False,  # RFC-622: hint that goal is a resume answer
        clarification_answers: list[str] | None = None,  # RFC-622: per-question answer list
        resume_interrupted: bool = False,  # daemon crash recovery admission
        goal_trace: Any | None = None,  # GoalLoopTrace when Langfuse enabled
        preamble: list[Any] | None = None,  # RFC-222 §Goal-Report-Pair Projection
        interaction_mode: str | None = None,  # per-goal "agent"|"ask"|"plan" graph selection
        approved_plan_path: str | None = None,  # Bug #3: plan-mode approve exec goal
    ) -> AsyncGenerator[tuple[str, Any], None]:
        """Run loop with progress events (RFC-0020 compliant).

        Yields progress events during execution for display.

        Args:
            goal: Goal description to execute
            thread_id: Thread context for execution
            workspace: Thread-specific workspace path (RFC-103)
            max_iterations: Maximum loop iterations (default: 8)
            loop_id: Optional loop_id (None → auto-generate UUID)
            intent: IntentClassification (RFC-225). When omitted, the graph entry
                ``intent_classify`` node runs classification with full CE ledger
                projection (prior-goal completion + preamble). Loop continuation is
                derived from the checkpoint.
            shared_pool: SharedPostgreSQLPool for high-concurrency.
                - new_goal: Normal goal execution flow
                - chitchat: Handled via in-graph fast-path and runner chitchat response
            routing_classification: ``RoutingClassification`` for CoreAgent middleware.
            clarification_policy: Optional ``ClarificationPolicy`` (RFC-622) used by
                the loop graph's ``await_clarification`` node. When ``None``, clarification
                requests are deferred via the legacy no-policy path.
            resume_interrupted: When True, skip the chitchat fast-path and recover
                the in-flight ``status=running`` goal without continue-keyword cancel.
            goal_trace: Optional pre-allocated ``GoalLoopTrace``; when omitted and Langfuse
                is enabled, one is opened before the graph runs so intake classification
                and ``strange-loop-graph`` share one pinned trace.
            preamble: Optional flattened list of ``BaseMessage`` (ancestor
                ``(user, ai)`` pairs) projected by the daemon's
                ``ContextProjector`` (RFC-222 §Goal-Report-Pair Projection).
                When present, seeded into the CE ledger (phase ``"preamble"``)
                after ``state.bind_ce`` and before the graph runs, so the
                executing LLM begins with a real multi-turn transcript. ``None``
                or empty → existing first-user-message path unchanged.

        Yields:
            Tuples of (event_type, event_data) for progress updates
        """
        from soothe_nano.skills.catalog import (
            parse_slash_skill_user_line,
            try_expand_slash_skill_user_line,
        )
        from soothe_nano.skills.workspace_sync import sync_specific_skill_to_workspace
        from soothe_nano.workspace.workspace_paths import (
            filesystem_virtual_mode_from_soothe_config,
        )

        goal_user_submission: str | None = None
        skill_context: str | None = None
        slash_invoked_skill_name: str | None = None
        slash_invoked_skill_body: str | None = None
        # Clarification answers are resume payloads only — never the turn goal text.
        # Original planning goal is restored from CE after load (below).
        execution_goal = "" if clarification_answer else goal

        # Targeted skill sync - only sync the addressed skill
        parsed_skill = None if clarification_answer else parse_slash_skill_user_line(goal)
        if workspace and filesystem_virtual_mode_from_soothe_config(self.config):
            if parsed_skill is not None:
                skill_name = parsed_skill[0]
                sync_specific_skill_to_workspace(self.config, workspace, skill_name)
            # If no skill addressed, skip sync (skills are synced on-demand via middleware)

        skill_env = (
            None
            if clarification_answer
            else try_expand_slash_skill_user_line(
                goal,
                self.config,
                workspace=str(workspace) if workspace else None,
            )
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
                "[StrangeLoop] /skill: user line did not expand (missing skill on this host "
                "or unreadable SKILL.md); CoreAgent will see the raw line: %s",
                log_preview(goal, 120),
            )

        # A ``/skill:`` submission owns execution: the skill body drives CoreAgent, so drop any
        # specialist routing hint before it reaches loop state, routing, or the runtime context.
        if parsed_skill is not None and (preferred_subagent or routing_classification):
            logger.info(
                "[Intent] Slash skill submitted; ignoring specialist routing hint (%s)",
                preferred_subagent,
            )
            preferred_subagent = None
            routing_classification = None

        # Initialize StrangeLoop state manager (RFC-205, loop_id parameter, config)
        # Pass shared_pool for high-concurrency support
        state_manager = StrangeLoopStateManager(
            loop_id,
            config=self.config,
            shared_pool=shared_pool,
        )
        # RFC-223: Main StrangeLoop thread id must align to loop_id.
        # Keep caller-provided thread_id for upstream intent/routing context, but normalize
        # all StrangeLoop checkpoint + execution thread bookkeeping to loop_id.
        main_thread_id = state_manager.loop_id
        if thread_id and thread_id != main_thread_id:
            logger.info(
                "[StrangeLoop] normalizing main thread_id to loop_id: input=%s loop_id=%s",
                thread_id,
                main_thread_id,
            )

        # Initialize checkpoint anchor manager (shared checkpoint pool in daemon/thread_pool mode)
        anchor_manager = await CheckpointAnchorManager.create(
            state_manager.loop_id,
            config=self.config,
        )

        runtime_ctx: LoopRuntimeContext | None = None
        try:
            preclassified_intent = intent
            checkpoint: Any = None

            active_goal_trace = goal_trace
            if (
                active_goal_trace is None
                and intent_classifier is not None
                and not clarification_answer
                and self.config.observability.langfuse.enabled
            ):
                active_goal_trace = SootheLangfuse(self.config).begin_goal_loop(
                    session_id=main_thread_id,
                    loop_id=state_manager.loop_id,
                )

            # Intake classification runs in the graph entry node (INTAKE) which
            # projects the full CE ledger (prior-goal completion + preamble) so
            # the second goal sees the first goal's context. The graph node
            # inherits the LangGraph RunnableConfig for tracing.
            checkpoint = await state_manager.load()

            # Try to recover from checkpoint (RFC-216: loop-scoped).

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
            # valid resume of a running checkpoint (structural plan-bootstrap guard)
            recovery_valid_resume = False
            goal_record = None
            iteration = 0

            if checkpoint and checkpoint.status == "running":
                current_goal_index = checkpoint.current_goal_index
                if 0 <= current_goal_index < len(checkpoint.goal_history):
                    goal_record = checkpoint.goal_history[current_goal_index]
                    exec_cp = checkpoint.execution_checkpoint or {}
                    iteration = int(exec_cp.get("iteration") or 0)
                    recovery_valid_resume = True
                    logger.info(
                        "Recovering from checkpoint at iteration %d (goal: %s)",
                        iteration,
                        goal_record.goal_id,
                    )
                elif checkpoint.goal_history and any(
                    g.status in ("completed", "failed", "cancelled")
                    for g in checkpoint.goal_history
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
                    # RFC-624 Phase 4 Step 3: seeding removed — CE ledger spans all goals
                    await state_manager.save(checkpoint, include_goal_history=True)
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
                    await state_manager.save(checkpoint, include_goal_history=True)
                    iteration = 0
                    recovery_valid_resume = False

            elif checkpoint and checkpoint.status == "idle":
                checkpoint.current_thread_id = main_thread_id
                if main_thread_id not in checkpoint.thread_ids:
                    checkpoint.thread_ids.append(main_thread_id)
                user_line_early = (goal_user_submission or goal or "").strip()
                # After cancel, interrupt touch may leave status=idle while the
                # StrangeLoop goal index entry is still running. Resume that goal in place
                # when the user sends retry/continue/resume instead of start_new_goal("retry").
                if (
                    not resume_interrupted
                    and not clarification_answer
                    and has_resumable_interrupted_goal(checkpoint)
                    and is_loop_control_signal(user_line_early)
                ):
                    goal_record = checkpoint.goal_history[checkpoint.current_goal_index]
                    if goal_record.status in ("cancelled", "interrupted"):
                        # Re-activate a cancelled (hard kill) or interrupted
                        # (user cancel via mark_goal_interrupted) goal so the
                        # loop resumes in place from the persisted iteration
                        # cursor rather than starting a fresh goal.
                        goal_record.status = "running"
                        goal_record.completed_at = None
                    exec_cp = checkpoint.execution_checkpoint or {}
                    iteration = int(exec_cp.get("iteration") or 0)
                    checkpoint.status = "running"
                    await state_manager.save(checkpoint, include_goal_history=True)
                    recovery_valid_resume = True
                    logger.info(
                        "Resuming interrupted goal after idle touch: loop=%s goal=%s iter=%d",
                        state_manager.loop_id,
                        goal_record.goal_id,
                        iteration,
                    )
                else:
                    goal_record = state_manager.start_new_goal(execution_goal, max_iterations)
                    checkpoint.goal_history.append(goal_record)
                    checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
                    checkpoint.status = "running"
                    # RFC-624 Phase 4 Step 3: seeding removed — CE ledger spans all goals
                    # via ce.load() which restores prior DAG + ledger state.
                    await state_manager.save(checkpoint, include_goal_history=True)
                    iteration = 0
                    logger.info(
                        "continued loop %s: new goal id=%s idx=%d",
                        state_manager.loop_id,
                        goal_record.goal_id,
                        checkpoint.current_goal_index,
                    )

            else:
                if checkpoint is not None:
                    logger.info(
                        "Starting fresh StrangeLoop checkpoint (prior status=%s loop_id=%s)",
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

                await state_manager.save(checkpoint, include_goal_history=True)

            user_submission_line = (goal_user_submission or goal or "").strip()
            # Interrupt-resume keywords resume the same goal in place. Idle-loop
            # continue keywords (without recovery) still bootstrap a new goal.
            interrupt_resume_in_place = (
                (not resume_interrupted)
                and recovery_valid_resume
                and is_loop_control_signal(user_submission_line)
            )
            force_continue_loop = (
                (not resume_interrupted)
                and is_continue_keyword(user_submission_line)
                and not interrupt_resume_in_place
            )
            if interrupt_resume_in_place and goal_record is not None:
                if goal_record.status == "cancelled":
                    goal_record.status = "running"
                    goal_record.completed_at = None
                    if checkpoint is not None:
                        checkpoint.status = "running"
                        await state_manager.save(checkpoint, include_goal_history=True)
                logger.info(
                    "[Goal] interrupt resume in place (goal=%s iter=%d signal=%s)",
                    goal_record.goal_id,
                    iteration,
                    log_preview(user_submission_line, 40),
                )

            # RFC-225: continue_loop when prior goal(s) exist beside the active one.
            continue_loop_mode = len(checkpoint.goal_history) >= 2

            # Client-forced intent (intake_scope) skips in-graph intake
            # classification; sync routing now. Otherwise the graph INTAKE node
            # classifies with full ledger context and sets intent itself.
            if preclassified_intent is not None:
                synced_routing = build_loop_routing_classification(
                    preclassified_intent,
                    preferred_subagent,
                )
                if synced_routing is not None:
                    routing_classification = synced_routing

            state = LoopState(
                goal=execution_goal,
                goal_user_submission=goal_user_submission,
                skill_context=skill_context,
                slash_invoked_skill_name=slash_invoked_skill_name,
                slash_invoked_skill_body=slash_invoked_skill_body,
                thread_id=main_thread_id,
                workspace=workspace,
                iteration=iteration,  # Use recovered or initial iteration
                max_iterations=max_iterations,
                intent=preclassified_intent,
                response_language=normalize_response_language(
                    getattr(preclassified_intent, "response_language", None)
                    if preclassified_intent is not None
                    else (
                        normalize_response_language(
                            getattr(
                                getattr(checkpoint, "loop_state", None),
                                "response_language",
                                None,
                            )
                        )
                        if clarification_answer and checkpoint is not None
                        else None
                    )
                ),
                routing_classification=routing_classification,
                loop_messages=[],  # RFC-624 Phase 4 Stage 2: CE ledger spans all goals
                approved_plan_path=approved_plan_path,
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

            if clarification_answer:
                logger.info(
                    "[Goal] clarification resume (max_iterations=%d, iteration=%d, "
                    "continue_loop=%s); restoring original goal from CE",
                    max_iterations,
                    state.iteration,
                    continue_loop_mode,
                )
            else:
                logger.info(
                    "[Goal] %s (max_iterations=%d, iteration=%d, continue_loop=%s)",
                    log_preview(execution_goal, 80),
                    max_iterations,
                    state.iteration,
                    continue_loop_mode,
                )

            from soothe.sloop.state.resume_topic import schedule_resume_topic_persistence
            from soothe.sloop.utils.goal_text import resolve_user_request

            if not clarification_answer:
                # Intake reasoning lives in the graph node now; the resume topic
                # falls back to the user's own words for all task results.
                schedule_resume_topic_persistence(
                    config=self.config,
                    loop_id=state_manager.loop_id,
                    intake_reasoning=None,
                    goal_text=resolve_user_request(state),
                    is_first_loop_goal=checkpoint.total_goals_completed == 0,
                )

            queue: asyncio.Queue[Any] = asyncio.Queue()
            _graph_sentinel = object()

            async def emit(event_type: str, event_data: Any) -> None:
                await queue.put((event_type, event_data))

            from soothe.sloop.clarification.runtime_factory import (
                bind_clarification_emit,
            )

            bind_clarification_emit(clarification_policy, emit)

            plan_manager: Any

            # RFC-624 Phase 4: ContextEngine is always active
            from soothe.context import StepPlanManagerAdapter
            from soothe.context.engine import ContextEngine as _ContextEngine
            from soothe.context.store_factory import (
                resolve_context_engine_persistence,
            )

            persistence_backend = self.config.persistence.default_backend

            persistence = resolve_context_engine_persistence(
                self.config,
                state_manager.loop_id,
            )

            # RFC-624 Phase 4: Loop-scoped CE lifecycle. Create once per
            # loop_id, persist across goals. On subsequent calls, reuse the
            # existing instance, load prior DAG, and add a new goal.
            if self._ce is None:
                self._ce = _ContextEngine(persistence=persistence)

            exec_ledger_cfg = self.config.agent.loop.execute_prompt_ledger
            self._ce.execute_ai_ledger_max_tokens = exec_ledger_cfg.execute_ai_ledger_max_tokens

            ce_instance = self._ce

            loaded = await ce_instance.load()

            if isinstance(loaded, Exception):
                logger.warning("[CE] load() failed: %s", loaded, exc_info=True)
                loaded = False
            if loaded:
                logger.info(
                    "ContextEngine loaded prior state (goals=%d, backend=%s)",
                    len(ce_instance.get_all_goals()),
                    persistence_backend,
                )

            if force_continue_loop and loaded:
                for prior in ce_instance.get_all_goals():
                    if prior.status == "active":
                        await ce_instance.cancel_goal(prior.id, reason="continue_keyword")
                await ce_instance.save()

            from soothe.sloop.utils.goal_text import (
                apply_clarification_resume_goal_text,
                resolve_clarification_resume_ce_goal,
                resolve_interrupt_resume_ce_goal,
                resolve_planning_goal,
            )

            ce_goal: Any = None
            if clarification_answer:
                ce_goal = resolve_clarification_resume_ce_goal(
                    ce_instance, loop_id=state_manager.loop_id
                )
                if ce_goal is not None:
                    original = apply_clarification_resume_goal_text(state, ce_goal)
                    if getattr(ce_goal, "status", None) == "pending":
                        await ce_instance.activate_goal(ce_goal.id, loop_id=state_manager.loop_id)
                    elif getattr(ce_goal, "assigned_loop_id", None) != state_manager.loop_id:
                        ce_goal.assigned_loop_id = state_manager.loop_id
                    logger.info(
                        "[Goal] clarification resume reused CE goal %s: %s",
                        ce_goal.id,
                        log_preview(original or "(empty)", 80),
                    )
                else:
                    logger.warning(
                        "[Goal] clarification resume found no active CE goal for loop=%s; "
                        "creating a new CE goal from restored state",
                        state_manager.loop_id,
                    )

            # resume interrupted work on the same CE goal + step DAG.
            if ce_goal is None and (
                interrupt_resume_in_place or (recovery_valid_resume and resume_interrupted)
            ):
                ce_goal = resolve_interrupt_resume_ce_goal(
                    ce_instance, loop_id=state_manager.loop_id
                )
                if ce_goal is not None:
                    try:
                        await ce_instance.resume_interrupted_goal(
                            ce_goal.id, loop_id=state_manager.loop_id
                        )
                    except Exception:
                        logger.warning(
                            "[Goal] CE resume_interrupted_goal failed for %s; falling back",
                            getattr(ce_goal, "id", None),
                            exc_info=True,
                        )
                        ce_goal = None
                    else:
                        original = apply_clarification_resume_goal_text(state, ce_goal)
                        _hydrate_previous_plan_from_ce(state, ce_goal)
                        # A bare resume keyword ("retry") must not take the chitchat
                        # fast-path to END — that would skip the resumed goal's
                        # remaining work. Only CHITCHAT/None need upgrading; under
                        # the unified workflow simple and minimal route to DISPATCH.
                        # At ROOT_EVAL, minimal skips Eval, simple uses an LLM
                        # decision, and complex runs the structural Eval gate.
                        if is_interrupt_resume_keyword(user_submission_line):
                            from soothe.sloop.intention.models import IntakeLabel

                            intent_obj = state.intent
                            label = (
                                getattr(intent_obj, "intake_label", None) if intent_obj else None
                            )
                            if label in (IntakeLabel.CHITCHAT, None) and intent_obj is not None:
                                intent_obj.intake_label = IntakeLabel.COMPLEX
                        logger.info(
                            "[Goal] interrupt resume reused CE goal %s: %s",
                            ce_goal.id,
                            log_preview(original or "(empty)", 80),
                        )

            if ce_goal is None:
                ce_goal = await ce_instance.create_goal(
                    resolve_planning_goal(state) or execution_goal,
                    generating_reasoning="StrangeLoop goal",
                    source="user",
                    max_iterations=max_iterations,
                )
                await ce_instance.activate_goal(ce_goal.id, loop_id=state_manager.loop_id)

            # Persist CE before the graph can park on ``await_user`` (plan review
            # / ask_user). Without this, clarification resume loads an
            # empty DAG and fabricates a blank CE goal.
            try:
                await ce_instance.save()
            except Exception:
                logger.warning(
                    "[CE] save after goal activate failed (loop=%s goal=%s)",
                    state_manager.loop_id,
                    getattr(ce_goal, "id", None),
                    exc_info=True,
                )

            # RFC-624 Phase 4 Step 3: bind CE to LoopState
            state.bind_ce(ce_instance, ce_goal.id)

            plan_manager = StepPlanManagerAdapter(
                subengine=ce_instance.planning.step,
                goal_id=ce_goal.id,
            )

            logger.info(
                "ContextEngine active (goal_id=%s, backend=%s)",
                ce_goal.id,
                persistence_backend,
            )

            # RFC-222 §Goal-Report-Pair Projection: seed ancestor (user, ai)
            # pairs into the CE ledger as a preamble transcript before the
            # graph runs. ``loop_messages`` is rebuilt from this ledger on
            # every access (RFC-214), so the pairs surface to the planner /
            # plan review / executor with no extra wiring. ``None``/empty → existing path.
            if preamble:
                from soothe.sloop.orchestrator.stations import PHASE_PREAMBLE

                seeded = 0
                for msg in preamble:
                    try:
                        await ce_instance.record_message(msg, phase=PHASE_PREAMBLE)
                        seeded += 1
                    except Exception:
                        logger.warning(
                            "[StrangeLoop] preamble seed dropped a message (loop=%s); continuing",
                            state_manager.loop_id,
                            exc_info=True,
                        )
                if seeded:
                    logger.info(
                        "[StrangeLoop] seeded %d preamble message(s) (loop=%s, goal=%s)",
                        seeded,
                        state_manager.loop_id,
                        ce_goal.id,
                    )

            ctx = LoopRuntimeContext(
                strange_loop=self,
                state_manager=state_manager,
                anchor_manager=anchor_manager,
                plan_manager=plan_manager,
                checkpoint=checkpoint,
                goal_record=goal_record,
                continue_loop_mode=continue_loop_mode,
                recovery_valid_resume=recovery_valid_resume,
                loop_state=state,
                emit=emit,
                intent_classifier=intent_classifier,
                preferred_subagent=preferred_subagent,
                interaction_mode=interaction_mode,
                clarification_policy=clarification_policy,
                clarification_resume_text=goal if clarification_answer else None,
                clarification_resume_answers=(
                    list(clarification_answers)
                    if clarification_answer and clarification_answers
                    else None
                ),
                ce=ce_instance,
                ce_goal_id=ce_goal.id,
                goal_trace=active_goal_trace,
            )
            runtime_ctx = ctx

            async def pump_graph() -> None:
                try:
                    from soothe.sloop.orchestrator.runner import (
                        invoke_strange_loop_graph,
                    )

                    await invoke_strange_loop_graph(ctx)
                except Exception as e:
                    # Check if this is a recoverable DB connection error
                    from soothe.sloop.checkpoints.retry_utils import (
                        is_recoverable_connection_error,
                    )

                    if is_recoverable_connection_error(e):
                        logger.error(
                            "[pump_graph] DB connection error after retries: %s: %s. "
                            "Emitting fatal_error event instead of crashing daemon.",
                            type(e).__name__,
                            e,
                        )
                        await queue.put(
                            (
                                "fatal_error",
                                {
                                    "error": f"Database connection lost: {type(e).__name__}",
                                },
                            )
                        )
                    else:
                        logger.error(
                            "[pump_graph] Graph execution error: %s: %s",
                            type(e).__name__,
                            e,
                            exc_info=True,
                        )
                        await queue.put(
                            (
                                "fatal_error",
                                {"error": str(e)},
                            )
                        )
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
                # Persist a resumable interruption cursor so ``retry`` / ``resume``
                # restores the iteration counter instead of restarting the goal.
                # Marking is best-effort: a second cancel during the save must not
                # mask the original cancellation propagating to the caller.
                if runtime_ctx is not None and runtime_ctx.goal_record is not None:
                    try:
                        await runtime_ctx.state_manager.mark_goal_interrupted(
                            runtime_ctx.goal_record,
                            iteration=runtime_ctx.loop_state.iteration,
                            reason="user_cancelled",
                        )
                    except Exception:
                        logger.warning(
                            "[run_with_progress] mark_goal_interrupted failed (loop=%s)",
                            runtime_ctx.state_manager.loop_id,
                            exc_info=True,
                        )
                raise
            finally:
                if not pump_task.done():
                    pump_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await pump_task
                else:
                    await pump_task

        finally:
            from soothe.sloop.stations.completion.finalize import (
                await_goal_completion_tail_persistence,
            )

            # Drain checkpoint finalize before closing pools so a background save cannot
            # restart the async flush worker and block the thread-pool worker cleanup.
            await await_goal_completion_tail_persistence(runtime_ctx)
            # Always stop async checkpoint worker even when setup fails before graph start.
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
        capabilities = None
        capability_reader = getattr(self.core_agent, "list_capabilities", None)
        if callable(capability_reader):
            capabilities = capability_reader()

        raw_tools = getattr(capabilities, "tools", ())
        if (
            not raw_tools
            and hasattr(self.core_agent, "tools")
            and isinstance(self.core_agent.tools, dict)
        ):
            raw_tools = tuple(str(name) for name in self.core_agent.tools.keys())
        available_tools = (
            [str(name) for name in raw_tools if isinstance(name, str)]
            if isinstance(raw_tools, (list, tuple, set))
            else []
        )

        from soothe.sloop.state.schemas import filter_task_catalog_subagent_names

        available_subagents = filter_task_catalog_subagent_names(
            [name for name, cfg in self.config.subagents.items() if cfg.enabled]
        )
        raw_subagents = getattr(capabilities, "subagents", ())
        capability_subagents = (
            [str(name) for name in raw_subagents if isinstance(name, str)]
            if isinstance(raw_subagents, (list, tuple, set))
            else []
        )
        for capability_subagent in filter_task_catalog_subagent_names(capability_subagents):
            if capability_subagent not in available_subagents:
                available_subagents.append(capability_subagent)

        completed_steps = [
            SdkStepResult(
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
            thread_id=state.thread_id,
        )
