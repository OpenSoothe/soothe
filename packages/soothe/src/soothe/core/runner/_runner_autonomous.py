"""Autonomous iteration loop mixin for SootheRunner (RFC-0007).

Extracted from ``runner.py`` to isolate the autonomous goal-driven
execution logic from the main runner orchestration.
"""

from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any

from soothe_sdk.core.exceptions import ConfigurationError

from soothe.config.constants import DEFAULT_AGENT_LOOP_MAX_ITERATIONS
from soothe.core.events import (
    LoopCompletedEvent,
    PlanCreatedEvent,
    PlanReflectedEvent,
)
from soothe.core.intention import IntentHint
from soothe.core.loop import AgentLoop
from soothe.core.loop.state.schemas import PlanResult
from soothe.core.loop.utils.messages import loop_assistant_messages_chunk

from ._runner_goal_directives import GoalDirectivesMixin
from ._runner_shared import _MIN_MEMORY_STORAGE_LENGTH, StreamChunk, _custom
from ._types import GoalResult

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

_BACKOFF_BASE_SECONDS = 2.0


class AutonomousMixin(GoalDirectivesMixin):
    """Autonomous iteration loop (RFC-0007, IG-155).

    Mixed into ``SootheRunner`` -- all ``self.*`` attributes are defined
    on the concrete class.  Inherits goal directive processing from
    ``GoalDirectivesMixin``.
    """

    async def initialize_autopilot(self, soothe_home: Path) -> None:
        """Initialize autopilot mode from goal files (RFC-200, IG-155).

        Args:
            soothe_home: Path to $SOOTHE_HOME
        """
        from soothe.core.goal_engine.discovery import discover_goals

        autopilot_dir = soothe_home / "autopilot"

        # Ensure directory structure exists
        autopilot_dir.mkdir(parents=True, exist_ok=True)
        (autopilot_dir / "goals").mkdir(exist_ok=True)

        # Discover goals from files
        goal_definitions = discover_goals(autopilot_dir)

        if not goal_definitions:
            logger.warning("No goals discovered from autopilot directory")
            return

        # Create goals in GoalEngine
        for goal_def in goal_definitions:
            try:
                await self._goal_engine.create_goal(
                    description=goal_def.description,
                    priority=goal_def.priority,
                    goal_id=goal_def.id,
                    depends_on=goal_def.depends_on,
                    source_file=str(goal_def.source_file) if goal_def.source_file else None,
                )
                logger.info("Loaded goal %s from file", goal_def.id)
            except Exception:
                logger.exception("Failed to create goal %s", goal_def.id)

    async def _run_autonomous(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
        workspace: str | None = None,
        max_iterations: int = 10,
        intent_hint: IntentHint | None = None,
    ) -> AsyncGenerator[StreamChunk]:
        """Autonomous iteration loop with DAG-based goal scheduling (RFC-0007, RFC-0009, IG-155).

        Creates goals, executes plans via the step loop, reflects, revises,
        and iterates until goals are complete or max_iterations is reached.
        Independent goals can run in parallel with isolated threads.

        IG-155: When user_input is empty, discovers goals from autopilot directory.

        Args:
            user_input: Goal description to execute.
            thread_id: Thread context for execution.
            workspace: Thread-specific workspace path.
            max_iterations: Maximum loop iterations.
            intent_hint: Suggested intent to bypass LLM classification.
        """
        import asyncio

        from soothe.config import SOOTHE_HOME

        from ._types import RunnerState

        if self._goal_engine is None:
            raise RuntimeError("Goal engine not initialized")

        state = RunnerState()
        state.thread_id = thread_id or self._current_thread_id or ""
        state.workspace = workspace

        # IG-155: Autopilot mode - discover goals from files when no input
        if not user_input or user_input.strip() == "":
            logger.info("Autopilot mode: discovering goals from files")
            await self.initialize_autopilot(SOOTHE_HOME)

            # Check if goals were discovered
            if not self._goal_engine.list_goals():
                # IG-271: Autopilot error event removed, replaced with logging
                logger.warning("Autopilot: No goals found in autopilot directory")
                return
        if self._intent_classifier:
            # IG-226: Load recent messages for conversation context
            await self._ensure_checkpointer_initialized()
            thread_id_for_context = state.thread_id or self._current_thread_id or ""
            recent = await self._load_recent_messages(thread_id_for_context, limit=6)

            # Get active goal if available (for thread continuation)
            active_goal_id = None
            active_goal_description = None
            if self._goal_engine:
                try:
                    goals = await self._goal_engine.list_goals(status="active")
                    if goals:
                        active_goal_id = goals[0].id
                        active_goal_description = goals[0].description
                except Exception:
                    logger.debug(
                        "Failed to get active goal for intent classification", exc_info=True
                    )

            # IG-226: Intent classification (priority over routing)
            intent_classification = await self._intent_classifier.classify_intent(
                user_input,
                recent_messages=recent,
                active_goal_id=active_goal_id,
                active_goal_description=active_goal_description,
                thread_id=thread_id_for_context,
                intent_hint=intent_hint,
            )

            logger.info(
                "Autonomous mode: intent_type=%s reuse_goal=%s - %s",
                intent_classification.intent_type,
                intent_classification.reuse_current_goal,
                user_input[:50],
            )

            # Store intent classification on state for goal creation logic
            state.intent_classification = intent_classification

            # Log intent classification (removed event emission)
            logger.info(
                "Intent: %s (confidence: %.2f)",
                intent_classification.intent_type,
                getattr(intent_classification, "confidence", 1.0),
            )

            # Fast path for quiz — skip goal engine and planning
            if intent_classification.intent_type == "quiz":
                async for chunk in self._run_quiz(
                    user_input, state.thread_id or "", classification=intent_classification
                ):
                    yield chunk
                return

            # IG-296: intent_classification is authoritative on runner state; AgentLoop uses
            # routing_classification (RoutingClassification) when entering the loop.
        else:
            state.intent_classification = None

        async for chunk in self._pre_stream_independent(user_input, state):
            yield chunk
        async for chunk in self._pre_stream_planning(user_input, state):
            yield chunk

        # IG-226: Intent-based goal creation
        # In autonomous mode, intent classification determines goal creation strategy
        intent = getattr(state, "intent_classification", None)

        goal = None
        if intent and hasattr(intent, "intent_type"):
            if intent.intent_type == "continue_thread":
                # Continue-thread: reuse active goal if available
                if intent.reuse_current_goal:
                    # Find active goal
                    active_goals = await self._goal_engine.list_goals(status="active")
                    if active_goals:
                        goal = active_goals[0]
                        logger.info(
                            "Continue-thread: reusing active goal %s",
                            goal.id,
                        )
                        logger.debug(
                            "Goal reused: %s | Description: %s", goal.id, goal.description[:50]
                        )
                    else:
                        # No active goal, create new goal despite continue_thread
                        logger.info("Continue-thread but no active goal, creating new goal")
                        goal = await self._goal_engine.create_goal(
                            intent.goal_description or user_input, priority=80
                        )
                else:
                    # Continue-thread without goal reuse - skip goal creation
                    logger.info("Continue-thread without goal, skipping goal creation")
                    # Proceed without goal lifecycle management
                    # AgentLoop will handle thread context continuation

            elif intent.intent_type == "new_goal":
                # New goal: create goal via GoalEngine
                goal_description = intent.goal_description or user_input
                goal = await self._goal_engine.create_goal(goal_description, priority=80)
                logger.info("New goal: created goal %s", goal.id)
        else:
            # No intent classification (disabled or fallback): create goal as before
            goal = await self._goal_engine.create_goal(user_input, priority=80)

        # Only emit goal created event if goal was actually created
        if goal and (not intent or intent.intent_type == "new_goal"):
            # IG-287: Include friendly message from intent classification
            friendly_message = intent.friendly_message if intent else None
            logger.info("Goal %s created: %s", goal.id, goal.description[:50])
            if friendly_message:
                logger.debug("Goal friendly message: %s", friendly_message[:100])

        from soothe.core.goal_engine.proposal_queue import ProposalQueue

        from ._types import IterationRecord

        iteration_records: list[IterationRecord] = []
        total_iterations = 0

        while total_iterations < max_iterations and not self._goal_engine.is_complete():
            self._proposal_queue = ProposalQueue()
            max_par_goals = self._concurrency.max_parallel_goals
            ready_goals = await self._goal_engine.ready_goals(limit=max_par_goals)
            if not ready_goals:
                logger.info("No more goals to process")
                break

            if len(ready_goals) > 1:
                logger.info(
                    "Goal batch: %d goals ready | IDs: %s",
                    len(ready_goals),
                    [g.id for g in ready_goals],
                )

            if len(ready_goals) == 1:
                g = ready_goals[0]
                async for chunk in self._execute_goal_via_autopilot(
                    g,
                    parent_state=state,
                    thread_id=state.thread_id,
                    user_input=user_input,
                    iteration_records=iteration_records,
                    total_iterations=total_iterations,
                    parallel_goals=1,
                ):
                    yield chunk
                total_iterations += 1
            else:
                collected: dict[str, list[StreamChunk]] = {}

                n_parallel = len(ready_goals)

                async def _run_goal(
                    g: Any,
                    _collected: dict[str, list[StreamChunk]] = collected,
                    _iters: int = total_iterations,
                    _n_par: int = n_parallel,
                ) -> None:
                    chunks: list[StreamChunk] = []
                    goal_tid = f"{state.thread_id}__goal_{g.id}"
                    async with self._concurrency.acquire_goal():
                        async for chunk in self._execute_goal_via_autopilot(
                            g,
                            parent_state=state,
                            thread_id=goal_tid,
                            user_input=user_input,
                            iteration_records=iteration_records,
                            total_iterations=_iters,
                            parallel_goals=_n_par,
                        ):
                            chunks.append(chunk)  # noqa: PERF401
                    _collected[g.id] = chunks

                results = await asyncio.gather(
                    *[_run_goal(g) for g in ready_goals],
                    return_exceptions=True,
                )
                for g, result in zip(ready_goals, results, strict=True):
                    if isinstance(result, Exception):
                        logger.exception("Goal %s failed: %s", g.id, result)
                        await self._goal_engine.fail_goal(g.id, error=str(result))
                        logger.info("Goal %s failed: %s", g.id, str(result)[:100])
                    else:
                        for chunk in collected.get(g.id, []):
                            yield chunk
                total_iterations += len(ready_goals)

        # Emit autonomous goal completion event for CLI (RFC-0010 / IG-027 / IG-273)
        root_report = getattr(goal, "report", None)
        if root_report and hasattr(root_report, "summary") and root_report.summary:
            summary = str(root_report.summary).strip()
            if summary:
                yield loop_assistant_messages_chunk(
                    content=summary,
                    phase="autonomous_goal",
                    thread_id=state.thread_id,
                )

        try:
            async for chunk in self._save_checkpoint(
                state,
                user_input=user_input,
                mode="autonomous",
                status="completed",
            ):
                yield chunk
            if state.artifact_store:
                state.artifact_store.update_status("completed")
            logger.debug("Thread saved: %s", state.thread_id)
        except Exception:
            logger.debug("Final state persistence failed", exc_info=True)

        # RFC-204: Check for scheduled tasks and enter dreaming mode if enabled
        if self._goal_engine and self._goal_engine.is_complete():
            await self._check_scheduled_and_dream(state, user_input)

        yield _custom(
            LoopCompletedEvent(loop_id=state.thread_id, thread_id=state.thread_id).to_dict()
        )

    async def _execute_goal_via_autopilot(
        self,
        goal: Any,
        *,
        parent_state: Any,
        thread_id: str,
        user_input: str,
        iteration_records: list[Any],
        total_iterations: int,
        parallel_goals: int = 1,
    ) -> AsyncGenerator[StreamChunk]:
        """Run ``_execute_autonomous_goal`` through ``AutopilotService.execute_goal`` (RFC-222).

        ``AutopilotService`` claims the goal, assigns a LoopHandle from its
        pool (with parent→child lineage reuse), stamps ``assigned_loop_id``
        on the Goal, sets the active-loop ContextVar so file-lock middleware
        can attribute lock ownership, and finalizes the loop on completion.

        Falls back to a direct call when ``AutopilotService`` is unavailable
        (e.g. some test harnesses construct the runner without the goal
        engine).
        """
        if self._autopilot_service is None:
            # Solo / test path: AutopilotService not constructed.
            async for chunk in self._execute_autonomous_goal(
                goal,
                parent_state=parent_state,
                thread_id=thread_id,
                user_input=user_input,
                iteration_records=iteration_records,
                total_iterations=total_iterations,
                parallel_goals=parallel_goals,
            ):
                yield chunk
            return

        def _executor(_goal: Any, _loop: Any) -> AsyncGenerator[StreamChunk]:
            # Bound closure so AutopilotService.execute_goal can drive it.
            return self._execute_autonomous_goal(
                _goal,
                parent_state=parent_state,
                thread_id=thread_id,
                user_input=user_input,
                iteration_records=iteration_records,
                total_iterations=total_iterations,
                parallel_goals=parallel_goals,
            )

        async for chunk in self._autopilot_service.execute_goal(goal.id, executor=_executor):
            yield chunk

    async def _execute_autonomous_goal(
        self,
        goal: Any,
        *,
        parent_state: Any,
        thread_id: str,
        user_input: str,
        iteration_records: list[Any],
        total_iterations: int,
        parallel_goals: int = 1,
    ) -> AsyncGenerator[StreamChunk]:
        """Execute a single goal through AgentLoop (RFC-200, IG-154).

        Delegates to AgentLoop.run() for single-goal execution with
        iterative refinement. Receives PlanResult and uses it for
        GoalEngine reflection with goal directives.

        Args:
            goal: Goal object to execute
            parent_state: Parent runner state
            thread_id: Thread ID for isolated execution
            user_input: Original user input
            iteration_records: Previous iteration records
            total_iterations: Current iteration number
            parallel_goals: Number of parallel goals executing
        """
        logger.info("Iteration %d started | Goal: %s", total_iterations, goal.id)

        iter_start = perf_counter()

        # IG-154: Delegate to AgentLoop when planner implements LoopPlannerProtocol
        if self._planner and hasattr(self._planner, "plan"):
            # Planner implements LoopPlannerProtocol - can delegate to AgentLoop
            logger.info(
                "[GoalEngine] Delegating goal %s to AgentLoop (thread=%s, max_iter=8)",
                goal.id,
                thread_id,
            )

            # Create AgentLoop instance for this goal
            agent_loop = AgentLoop(
                core_agent=self._agent,
                loop_planner=self._planner,
                config=self._config,
            )

            # IG-406: Get shared PostgreSQL pool for high-concurrency support
            shared_pool = await self.get_agentloop_shared_pool()

            # RFC-214: Prior conversation is now in loop_messages ledger, not separate excerpts
            await self._ensure_checkpointer_initialized()

            # Use AgentLoop.run_with_progress() to get streaming events
            goal_result = None
            from soothe.core.intention import build_loop_routing_classification

            intent_for_loop = getattr(parent_state, "intent_classification", None)
            routing_for_loop = build_loop_routing_classification(intent_for_loop, None)
            recent_for_classify = await self._load_recent_messages(thread_id, limit=6)

            async for event_type, event_data in agent_loop.run_with_progress(
                goal=goal.description,
                thread_id=thread_id,
                loop_id=thread_id,
                workspace=getattr(parent_state, "workspace", None),
                git_status=getattr(parent_state, "git_status", None),
                max_iterations=DEFAULT_AGENT_LOOP_MAX_ITERATIONS,  # AgentLoop iteration budget
                intent=intent_for_loop,
                routing_classification=routing_for_loop,
                intent_classifier=self._intent_classifier,
                recent_messages_for_intent=recent_for_classify,
                active_goal_id_for_intent=goal.id,
                active_goal_description_for_intent=goal.description,
                shared_pool=shared_pool,  # IG-406: Shared pool for high-concurrency
            ):
                # Propagate AgentLoop events to autonomous stream
                if event_type == "intent_fast_path":
                    classification = (
                        event_data.get("classification") if isinstance(event_data, dict) else None
                    )
                    intent_type = (
                        event_data.get("intent_type") if isinstance(event_data, dict) else None
                    )
                    if intent_type == "quiz":
                        async for chunk in self._run_quiz(
                            goal.description, thread_id, classification=classification
                        ):
                            yield chunk
                        goal_result = GoalResult(
                            goal_id=goal.id,
                            status="completed",
                            evidence_summary="Handled via intent fast path",
                            goal_progress="complete",
                            full_output="",
                            iteration_count=0,
                        )
                        break
                elif event_type == "completed":
                    plan_result = event_data.get("result")
                    if isinstance(plan_result, PlanResult):
                        goal_result = GoalResult(
                            goal_id=goal.id,
                            status="completed" if plan_result.is_done() else "failed",
                            evidence_summary=plan_result.evidence_summary,
                            goal_progress=plan_result.goal_progress,
                            full_output=plan_result.full_output,
                            iteration_count=event_data.get("iteration", 0),
                        )
                elif event_type == "plan":
                    # Emit plan event
                    yield _custom(
                        PlanCreatedEvent(
                            plan_id=f"P_{goal.plan_count}",
                            goal=goal.description,
                            steps=[],
                            reasoning=event_data.get("next_action", ""),
                            is_plan_only=False,
                        ).to_dict()
                    )
                elif event_type == "iteration_started":
                    # Propagate iteration events
                    yield event_data

            # If AgentLoop completed successfully, process result
            if goal_result:
                duration_ms = int((perf_counter() - iter_start) * 1000)
                goal_result.duration_ms = duration_ms

                # Emit goal report (removed event emission)
                logger.debug(
                    "Goal %s report: %d steps | Status: %s | Summary: %s",
                    goal.id,
                    goal_result.iteration_count,
                    goal_result.status,
                    goal_result.evidence_summary[:50],
                )

                # Update goal report
                from soothe.protocols.planner import GoalReport

                goal.report = GoalReport(
                    goal_id=goal.id,
                    description=goal.description,
                    summary=goal_result.full_output or goal_result.evidence_summary,
                    status=goal_result.status,
                )

                # Complete or fail goal based on PlanResult
                if goal_result.status == "completed":
                    await self._goal_engine.complete_goal(goal.id)
                    logger.info("Goal %s completed", goal.id)
                else:
                    await self._goal_engine.fail_goal(
                        goal.id, error="AgentLoop did not achieve goal"
                    )
                    logger.info(
                        "Goal %s failed: Not achieved (retry %d)", goal.id, goal.retry_count
                    )

                # Store memory
                if (
                    self._memory
                    and goal_result.evidence_summary
                    and len(goal_result.evidence_summary) > _MIN_MEMORY_STORAGE_LENGTH
                ):
                    try:
                        from soothe.protocols.memory import MemoryItem

                        await self._memory.remember(
                            MemoryItem(
                                content=goal_result.evidence_summary[:500],
                                tags=["agent_response", "goal_" + goal.id],
                                source_thread=parent_state.thread_id,
                            )
                        )
                    except Exception:
                        logger.debug("Memory storage failed", exc_info=True)

                # GoalEngine reflection with AgentLoop result
                reflection = None
                if self._planner and self._goal_engine:
                    try:
                        from soothe.protocols.planner import GoalContext, GoalSnapshot

                        all_goals = await self._goal_engine.list_goals()
                        goal_context = GoalContext(
                            current_goal_id=goal.id,
                            all_goals=[
                                GoalSnapshot(**g.model_dump(mode="json")) for g in all_goals
                            ],
                            completed_goals=[g.id for g in all_goals if g.status == "completed"],
                            failed_goals=[g.id for g in all_goals if g.status == "failed"],
                            ready_goals=[
                                g.id for g in all_goals if g.status in ("pending", "active")
                            ],
                            max_parallel_goals=self._concurrency.max_parallel_goals,
                        )

                        # Reflection with AgentLoop result
                        reflection = await self._planner.reflect(
                            plan=None,  # AgentLoop handled planning
                            step_results=[],  # AgentLoop handled execution
                            goal_context=goal_context,
                            agentloop_result=goal_result,  # IG-154: Pass AgentLoop result
                        )

                        yield _custom(
                            PlanReflectedEvent(
                                should_revise=reflection.should_revise,
                                assessment=reflection.assessment[:200],
                            ).to_dict()
                        )

                        # Process goal directives
                        if reflection.goal_directives:
                            goal_changes = await self._process_goal_directives(
                                reflection.goal_directives,
                                current_goal=goal,
                            )

                            logger.debug(
                                "Goal %s directives: %d applied | Changes: %s",
                                goal.id,
                                len(reflection.goal_directives),
                                str(goal_changes)[:50] if goal_changes else "none",
                            )

                            # Check if current goal dependencies still satisfied
                            if goal.depends_on:
                                all_goals_dict = {g.id: g for g in all_goals}
                                deps_satisfied = all(
                                    all_goals_dict.get(dep_id)
                                    and all_goals_dict[dep_id].status == "completed"
                                    for dep_id in goal.depends_on
                                    if dep_id in all_goals_dict
                                )

                                if not deps_satisfied:
                                    logger.info(
                                        "Goal %s dependencies no longer satisfied after directives, deferring",
                                        goal.id,
                                    )
                                    # Reset goal to pending
                                    goal.status = "pending"
                                    logger.info(
                                        "Goal %s deferred: Dependencies added but not completed",
                                        goal.id,
                                    )

                            # Save checkpoint after goal mutations
                            async for chunk in self._save_checkpoint(
                                parent_state,
                                user_input=user_input,
                                mode="autonomous",
                            ):
                                yield chunk

                    except Exception:
                        logger.debug("GoalEngine reflection failed", exc_info=True)

                # Emit iteration completed (removed event emission)
                duration_ms = int((perf_counter() - iter_start) * 1000)
                logger.debug(
                    "Iteration %d completed | Goal: %s | Outcome: %s | Duration: %dms",
                    total_iterations,
                    goal.id,
                    goal_result.status,
                    duration_ms,
                )

                # Return early - AgentLoop handled everything
                return

            logger.error(
                "AgentLoop produced no goal_result for goal %s (check loop graph / events)",
                goal.id,
            )
            if self._goal_engine:
                await self._goal_engine.fail_goal(
                    goal.id, error="AgentLoop produced no goal_result"
                )
            return

        _planner_required_msg = (
            "Autonomous goal execution requires a planner implementing LoopPlannerProtocol.plan "
            "(AgentLoop). Legacy direct CoreAgent streaming has been removed."
        )
        logger.error("%s goal_id=%s", _planner_required_msg, goal.id)
        raise ConfigurationError(_planner_required_msg)

    async def _process_proposals(
        self,
        goal_id: str,
        proposal_queue: Any,  # ProposalQueue
    ) -> None:
        """RFC-204: Process proposals queued by Layer 2 tools after iteration.

        Applies each proposal based on type:
        - report_progress → append to goal progress section
        - suggest_goal → evaluate criticality, create if approved
        - add_finding → append to findings
        - flag_blocker → transition goal to blocked state

        Args:
            goal_id: Current goal ID.
            proposal_queue: ProposalQueue instance to drain.
        """
        proposals = proposal_queue.drain()
        if not proposals:
            return

        logger.info("Processing %d proposals for goal %s", len(proposals), goal_id)

        for proposal in proposals:
            try:
                if proposal.type == "report_progress":
                    payload = proposal.payload
                    entry = (
                        f"{payload.get('status', 'update')}: {payload.get('findings', '')[:200]}"
                    )
                    if self._goal_engine:
                        await self._goal_engine.append_goal_progress(goal_id, entry)

                elif proposal.type == "suggest_goal":
                    await self._handle_suggested_goal(proposal)

                elif proposal.type == "add_finding":
                    # Findings tracked in Layer 2 checkpoint, no context ingestion
                    pass

                elif proposal.type == "flag_blocker":
                    reason = proposal.payload.get("reason", "Unknown blocker")
                    if self._goal_engine:
                        await self._goal_engine.block_goal(goal_id, reason=reason)
                    # IG-271: Autopilot blocking event removed, replaced with logging
                    logger.debug("Goal %s blocking: %s", goal_id, reason[:200])

            except Exception:
                logger.debug("Failed to process proposal: %s", proposal.type, exc_info=True)

    async def _handle_suggested_goal(self, proposal: Any) -> None:
        """RFC-204: Handle a suggested goal proposal with criticality check.

        If goal is evaluated as 'must', it queues for user confirmation.
        Otherwise it creates the goal immediately.

        Args:
            proposal: Proposal with type 'suggest_goal'.
        """
        from soothe.core.goal_engine.criticality import evaluate_criticality_async

        description = proposal.payload.get("description", "")
        priority = proposal.payload.get("priority", 50)

        if not description:
            return

        sem_cfg = None
        if self._config and hasattr(self._config, "optimization"):
            sem_cfg = self._config.optimization.semantic_risk

        # Build context for risk assessment (workspace helps evaluate danger level)
        context_parts: list[str] = []
        workspace = getattr(self._state, "workspace", None) if hasattr(self, "_state") else None
        if workspace:
            context_parts.append(f"Workspace: {workspace}")
        context = " | ".join(context_parts) if context_parts else None

        result = await evaluate_criticality_async(
            description,
            priority,
            use_llm=True,
            model=getattr(self, "_model", None),
            use_semantic=sem_cfg.enabled if sem_cfg else False,
            semantic_config=sem_cfg,
            soothe_config=self._config,
            context=context,
        )

        if result.is_must:
            # Queue for user confirmation
            await self._queue_must_confirmation(description, priority, result.reasons)
        # Create goal immediately
        elif self._goal_engine:
            goal = await self._goal_engine.create_goal(description, priority=priority)
            logger.info(
                "Suggested goal created: %s (criticality=%s)",
                goal.id,
                result.level,
            )

    async def _queue_must_confirmation(
        self, description: str, priority: int, reasons: list[str]
    ) -> None:
        """RFC-204: Queue a MUST goal for user confirmation.

        Writes to pending_confirmations.json and sends via channel outbox.

        Args:
            description: Goal description.
            priority: Goal priority.
            reasons: Criticality reasons.
        """
        import json
        import uuid
        from datetime import UTC, datetime

        from soothe.config import SOOTHE_HOME

        autopilot_dir = SOOTHE_HOME / "autopilot"
        confirmations_file = autopilot_dir / "pending_confirmations.json"
        confirmations_file.parent.mkdir(parents=True, exist_ok=True)

        confirmation = {
            "id": uuid.uuid4().hex[:12],
            "description": description,
            "priority": priority,
            "reasons": reasons,
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "status": "pending",
        }

        # Read existing confirmations
        existing: list[dict] = []
        if confirmations_file.exists():
            try:
                existing = json.loads(confirmations_file.read_text())
            except (json.JSONDecodeError, OSError):
                existing = []

        existing.append(confirmation)
        confirmations_file.write_text(json.dumps(existing, indent=2))

        # Send via channel outbox
        try:
            from soothe.core.channel.models import ChannelMessage
            from soothe.core.channel.outbox import ChannelOutbox

            outbox = ChannelOutbox(autopilot_dir / "outbox")
            msg = ChannelMessage(
                type="must_goal_confirmation",
                payload=confirmation,
                sender="soothe",
                requires_ack=True,
            )
            outbox.send(msg)
        except Exception:
            logger.debug("Failed to send MUST confirmation via channel", exc_info=True)

        logger.info(
            "MUST goal queued for confirmation: %s (reasons: %s)",
            description[:80],
            ", ".join(reasons[:3]),
        )

    async def _send_autopilot_webhook(self, event_type: str, payload: dict) -> None:
        """Send autopilot webhook notification for an event.

        Args:
            event_type: Event type (e.g., "goal_completed", "goal_failed").
            payload: Event-specific payload dict.
        """
        try:
            from soothe.core.goal_engine.webhooks import WebhookConfig, WebhookService

            webhook_url = None
            if self._config and hasattr(self._config.agent, "autonomous"):
                webhook_url = self._config.agent.autonomous.webhooks.get(f"on_{event_type}")

            if not webhook_url:
                return

            service = WebhookService(
                webhooks={
                    event_type: [WebhookConfig(url=webhook_url)],
                }
            )
            await service.notify(event_type, payload)
        except Exception:
            logger.debug("Webhook failed for %s", event_type, exc_info=True)

    async def _detect_relationships_for_goal(self, completed_goal: Any) -> list[dict]:
        """RFC-204: Auto-detect relationships after goal completion.

        Returns list of event dicts to yield to the caller.

        Args:
            completed_goal: The goal that just completed.

        Returns:
            List of custom event dicts for detected relationships.
        """
        if not self._goal_engine:
            return []

        try:
            from soothe.core.goal_engine.relationship_detector import auto_apply_relationships
            from soothe.core.goal_engine.semantic_relationship_detector import (
                detect_relationships_async,
            )

            all_goals = await self._goal_engine.list_goals()
            rel_cfg = None
            if self._config and hasattr(self._config, "optimization"):
                rel_cfg = self._config.optimization.semantic_relationships

            relationships = await detect_relationships_async(
                completed_goal,
                all_goals,
                config=rel_cfg,
            )
            if not relationships:
                return []

            # IG-271: Relationship detecting events removed, replaced with logging
            for rel in relationships:
                logger.info(
                    "Relationship detected: %s %s %s (confidence=%.2f)",
                    rel.from_goal,
                    rel.rel_type,
                    rel.to_goal,
                    rel.confidence,
                )

            auto_apply_relationships(relationships, all_goals)
        except Exception:
            logger.debug("Relationship detection failed", exc_info=True)
            return []

        # Return empty list (no events emitted per IG-271)
        return []

    async def _check_scheduled_and_dream(
        self,
        state: Any,  # noqa: ARG002
        user_input: str,  # noqa: ARG002
    ) -> None:
        """RFC-204: Check for scheduled tasks, enter dreaming if none found.

        Args:
            state: Current runner state (unused, reserved for future).
            user_input: Original user input string (unused, reserved).
        """
        from soothe.config import SOOTHE_HOME

        autopilot_dir = SOOTHE_HOME / "autopilot"
        if not autopilot_dir.exists():
            return

        # Check for scheduled tasks
        try:
            from soothe.core.goal_engine import SchedulerService

            persist_path = autopilot_dir / "scheduler.json"
            scheduler = SchedulerService(persist_path=str(persist_path))
            due_tasks = scheduler.get_due_tasks()

            if due_tasks:
                task = due_tasks[0]
                scheduler.mark_running(task.id)
                logger.info("Autopilot resuming from scheduled task: %s", task.id)

                # Create goal from scheduled task and run it
                if self._goal_engine:
                    await self._goal_engine.create_goal(
                        description=task.description,
                        priority=task.priority,
                    )
                    scheduler.mark_completed(task.id)
                return
        except Exception:
            logger.debug("Scheduler check failed", exc_info=True)

        # No scheduled tasks — enter dreaming mode
        try:
            from soothe.core.goal_engine.dreaming import DreamingMode

            dreaming = DreamingMode(
                soothe_home=SOOTHE_HOME,
                memory_protocol=self._memory,
            )
            logger.info("Entering autopilot dreaming mode")

            # RFC-204: Emit dreaming events via WebSocket and webhook
            await self._send_autopilot_webhook("dreaming_entered", {})
            await dreaming.run()
            await self._send_autopilot_webhook("dreaming_exited", {})
        except Exception:
            logger.debug("Dreaming mode failed to start", exc_info=True)
