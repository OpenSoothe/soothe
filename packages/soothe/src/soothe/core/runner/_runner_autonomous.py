"""Autonomous iteration loop mixin for SootheRunner (RFC-0007, RFC-0009).

Extracted from ``runner.py`` to isolate the autonomous goal-driven
execution logic from the main runner orchestration.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any

from soothe.cognition.agent_loop import AgentLoop
from soothe.cognition.agent_loop.state.schemas import PlanResult
from soothe.config.constants import DEFAULT_AGENT_LOOP_MAX_ITERATIONS
from soothe.core.event_catalog import (
    AutonomousGoalCompletionEvent,
    GoalFailedEvent,
    PlanCreatedEvent,
    PlanReflectedEvent,
    ThreadEndedEvent,
)
from soothe.protocols.planner import StepResult

from ._runner_goal_directives import GoalDirectivesMixin
from ._runner_shared import _MIN_MEMORY_STORAGE_LENGTH, StreamChunk, _custom
from ._types import GoalResult

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

_BACKOFF_BASE_SECONDS = 2.0


class AutonomousMixin(GoalDirectivesMixin):
    """Autonomous iteration loop (RFC-0007, RFC-0009, IG-155).

    Mixed into ``SootheRunner`` -- all ``self.*`` attributes are defined
    on the concrete class.  Inherits goal directive processing from
    ``GoalDirectivesMixin``.
    """

    async def initialize_autopilot(self, soothe_home: Path) -> None:
        """Initialize autopilot mode from goal files (RFC-200, IG-155).

        Args:
            soothe_home: Path to $SOOTHE_HOME
        """
        from soothe.cognition.goal_engine.discovery import discover_goals

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
    ) -> AsyncGenerator[StreamChunk]:
        """Autonomous iteration loop with DAG-based goal scheduling (RFC-0007, RFC-0009, IG-155).

        Creates goals, executes plans via the step loop, reflects, revises,
        and iterates until goals are complete or max_iterations is reached.
        Independent goals can run in parallel with isolated threads.

        IG-155: When user_input is empty, discovers goals from autopilot directory.
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
            )

            logger.info(
                "[IG-226] Autonomous mode: intent_type=%s reuse_goal=%s - %s",
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

            # Fast path for chitchat - skip goal engine and planning
            if intent_classification.intent_type == "chitchat":
                async for chunk in self._run_chitchat(
                    user_input, state.thread_id or "", classification=intent_classification
                ):
                    yield chunk
                return

            # Fast path for quiz (IG-250) - skip goal engine and planning
            if intent_classification.intent_type == "quiz":
                async for chunk in self._run_quiz(
                    user_input, state.thread_id or "", classification=intent_classification
                ):
                    yield chunk
                return

            # Convert IntentClassification to RoutingClassification for routing
            state.unified_classification = intent_classification.to_routing_classification()
        else:
            state.unified_classification = None
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
            if intent.intent_type == "thread_continuation":
                # Thread continuation: reuse active goal if available
                if intent.reuse_current_goal:
                    # Find active goal
                    active_goals = await self._goal_engine.list_goals(status="active")
                    if active_goals:
                        goal = active_goals[0]
                        logger.info(
                            "[IG-226] Thread continuation: reusing active goal %s",
                            goal.id,
                        )
                        logger.debug(
                            "Goal reused: %s | Description: %s", goal.id, goal.description[:50]
                        )
                    else:
                        # No active goal, create new goal despite thread_continuation
                        logger.info(
                            "[IG-226] Thread continuation but no active goal, creating new goal"
                        )
                        goal = await self._goal_engine.create_goal(
                            intent.goal_description or user_input, priority=80
                        )
                else:
                    # Thread continuation without goal reuse - skip goal creation
                    logger.info("[IG-226] Thread continuation without goal, skipping goal creation")
                    # Proceed without goal lifecycle management
                    # AgentLoop will handle thread context continuation

            elif intent.intent_type == "new_goal":
                # New goal: create goal via GoalEngine
                goal_description = intent.goal_description or user_input
                goal = await self._goal_engine.create_goal(goal_description, priority=80)
                logger.info("[IG-226] New goal: created goal %s", goal.id)
        else:
            # No intent classification (disabled or fallback): create goal as before
            goal = await self._goal_engine.create_goal(user_input, priority=80)

        # Only emit goal created event if goal was actually created
        if goal and (not intent or intent.intent_type == "new_goal"):
            # IG-262: Include friendly message from intent classification
            friendly_message = intent.friendly_message if intent else None
            logger.info("Goal %s created: %s", goal.id, goal.description[:50])
            if friendly_message:
                logger.debug("Goal friendly message: %s", friendly_message[:100])

        from soothe.cognition.goal_engine.proposal_queue import ProposalQueue

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
                async for chunk in self._execute_autonomous_goal(
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
                        async for chunk in self._execute_autonomous_goal(
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
            yield _custom(
                AutonomousGoalCompletionEvent(
                    goal_id=goal.id,
                    description=goal.description,
                    status=root_report.status,
                    summary=root_report.summary,
                ).to_dict()
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

        yield _custom(ThreadEndedEvent(thread_id=state.thread_id).to_dict())

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
        import asyncio

        from ._types import IterationRecord, RunnerState

        logger.info("Iteration %d started | Goal: %s", total_iterations, goal.id)

        iter_start = perf_counter()
        current_input = goal.description

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

            # Prior Human/Assistant turns for Plan phase (same thread as IG-128 / IG-198)
            await self._ensure_checkpointer_initialized()
            prior_limit = self._config.agentic.prior_conversation_limit if self._config else 10
            recent_for_thread = await self._load_recent_messages(thread_id, limit=16)
            plan_excerpts = self._format_thread_messages_for_plan(
                recent_for_thread, limit=prior_limit
            )

            # Use AgentLoop.run_with_progress() to get streaming events
            goal_result = None
            async for event_type, event_data in agent_loop.run_with_progress(
                goal=goal.description,
                thread_id=thread_id,
                workspace=getattr(parent_state, "workspace", None),
                git_status=getattr(parent_state, "git_status", None),
                max_iterations=DEFAULT_AGENT_LOOP_MAX_ITERATIONS,  # AgentLoop iteration budget
                plan_conversation_excerpts=plan_excerpts,
            ):
                # Propagate AgentLoop events to autonomous stream
                if event_type == "completed":
                    plan_result = event_data.get("result")
                    if isinstance(plan_result, PlanResult):
                        goal_result = GoalResult(
                            goal_id=goal.id,
                            status="completed" if plan_result.is_done() else "failed",
                            evidence_summary=plan_result.evidence_summary,
                            goal_progress=plan_result.goal_progress,
                            confidence=plan_result.confidence,
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

        # Fallback: Non-AgentLoop execution path
        # For goals without LoopPlannerProtocol planner
        logger.warning(
            "[GoalEngine] Using legacy execution path (no AgentLoop) for goal %s - violates RFC architecture",
            goal.id,
        )

        # IG-271: Replace iteration event with compact logging
        logger.info("Iteration %d started | Goal: %s", total_iterations, goal.id)

        try:
            iter_state = RunnerState()
            canonical_tid = parent_state.thread_id
            iter_state.thread_id = canonical_tid
            iter_state.langgraph_thread_id = thread_id if thread_id != canonical_tid else None
            iter_state.workspace = getattr(parent_state, "workspace", None)
            self._ensure_runner_state_workspace(iter_state)
            self._ensure_artifact_store(iter_state)
            iter_state.unified_classification = parent_state.unified_classification
            iter_state.context_projection = getattr(parent_state, "context_projection", None)
            iter_state.recalled_memories = list(
                getattr(parent_state, "recalled_memories", []) or []
            )
            iter_state.observation_scope_key = getattr(parent_state, "observation_scope_key", "")

            should_refresh_observation = getattr(
                parent_state, "observation_refresh_needed", False
            ) or not (iter_state.context_projection is not None or iter_state.recalled_memories)

            if should_refresh_observation and self._memory:
                try:
                    items = await self._memory.recall(current_input, limit=5)
                    iter_state.recalled_memories = items
                except Exception:
                    logger.debug("Memory recall failed", exc_info=True)

            if should_refresh_observation:
                iter_state.observation_scope_key = current_input

            parent_state.context_projection = iter_state.context_projection
            parent_state.recalled_memories = list(iter_state.recalled_memories)
            parent_state.observation_scope_key = iter_state.observation_scope_key
            parent_state.observation_refresh_needed = False

            # Legacy: Direct step execution (bypasses AgentLoop)
            if iter_state.plan and len(iter_state.plan.steps) > 1:
                async for chunk in self._run_step_loop(
                    current_input, iter_state, iter_state.plan, goal_id=goal.id
                ):
                    yield chunk
            else:
                async with self._concurrency.acquire_llm_call():
                    async for chunk in self._stream_phase(current_input, iter_state):
                        yield chunk

            response_text = "".join(iter_state.full_response)

            if self._memory and response_text and len(response_text) > _MIN_MEMORY_STORAGE_LENGTH:
                try:
                    from soothe.protocols.memory import MemoryItem

                    await self._memory.remember(
                        MemoryItem(
                            content=response_text[:500],
                            tags=["agent_response"],
                            source_thread=canonical_tid,
                        )
                    )
                except Exception:
                    logger.debug("Memory storage failed", exc_info=True)

            reflection = None
            if self._planner and iter_state.plan and response_text:
                try:
                    step_results = [
                        StepResult(
                            step_id=s.id,
                            success=s.status == "completed",
                            outcome={
                                "type": "generic",
                                "size_bytes": len((s.result or "").encode("utf-8")),
                            },  # RFC-211
                            duration_ms=0,
                            thread_id=goal.thread_id,
                        )
                        for s in iter_state.plan.steps
                        if s.status in ("completed", "failed")
                    ]
                    if step_results:
                        # Build goal context for reflection (RFC-0007 §5.4)
                        goal_context = None
                        if self._goal_engine:
                            from soothe.protocols.planner import GoalContext

                            all_goals = await self._goal_engine.list_goals()
                            goal_context = GoalContext(
                                current_goal_id=goal.id,
                                all_goals=[g.model_dump(mode="json") for g in all_goals],
                                completed_goals=[
                                    g.id for g in all_goals if g.status == "completed"
                                ],
                                failed_goals=[g.id for g in all_goals if g.status == "failed"],
                                ready_goals=[
                                    g.id for g in all_goals if g.status in ("pending", "active")
                                ],
                                max_parallel_goals=self._concurrency.max_parallel_goals,
                            )

                        reflection = await self._planner.reflect(
                            iter_state.plan, step_results, goal_context
                        )
                        yield _custom(
                            PlanReflectedEvent(
                                should_revise=reflection.should_revise,
                                assessment=reflection.assessment[:200],
                            ).to_dict()
                        )

                        # Process goal directives from reflection (RFC-0007 §5.4)
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

                            # CRITICAL: Handle DAG state changes
                            # If the current goal now has unmet dependencies, reset it to pending
                            # and abort the current iteration
                            should_abort = await self._check_goal_dag_consistency(goal)

                            if should_abort:
                                logger.info(
                                    "Goal %s now has unmet dependencies, resetting to pending",
                                    goal.id,
                                )
                                goal.status = "pending"
                                goal.updated_at = datetime.now(UTC)

                                # Note: The plan and any completed steps remain attached to this goal.
                                # When the goal is rescheduled after its dependencies complete,
                                # the planner can decide whether to create a new plan or revise the existing one.
                                # The existing plan provides context for the next iteration.

                                logger.info("Goal %s deferred: Dependencies added", goal.id)

                                # Save checkpoint and exit - scheduler will pick up prerequisite goals
                                async for chunk in self._save_checkpoint(
                                    parent_state, user_input=user_input, mode="autonomous"
                                ):
                                    yield chunk
                                return  # Exit _execute_autonomous_goal early

                            # Save checkpoint after goal mutations
                            async for chunk in self._save_checkpoint(
                                parent_state, user_input=user_input, mode="autonomous"
                            ):
                                yield chunk
                except Exception:
                    logger.debug("Plan reflection failed", exc_info=True)

            plan_summary = ""
            if iter_state.plan:
                plan_summary = f"{iter_state.plan.goal}: " + "; ".join(
                    s.description for s in iter_state.plan.steps[:5]
                )

            should_continue = reflection.should_revise if reflection else False

            # RFC-204: Consensus loop — validate goal completion before accepting
            if self._goal_engine and self._model and not should_continue:
                from soothe.cognition.goal_engine.consensus import evaluate_goal_completion

                success_criteria = getattr(goal, "_success_criteria", None)
                c_decision, c_reasoning = await evaluate_goal_completion(
                    goal_description=goal.description,
                    response_text=response_text,
                    evidence_summary=plan_summary[:500],
                    success_criteria=success_criteria,
                    model=self._model,
                )

                if c_decision == "send_back":
                    sb_count = getattr(goal, "send_back_count", 0)
                    max_sb = getattr(goal, "max_send_backs", 3)

                    if sb_count < max_sb:
                        goal.send_back_count = sb_count + 1
                        logger.info(
                            "Goal %s sent back (%d/%d): %s",
                            goal.id,
                            goal.send_back_count,
                            max_sb,
                            c_reasoning[:100],
                        )
                        # Re-enter loop with refined instruction
                        current_input = f"Previous attempt did not satisfy goal. Feedback: {c_reasoning}. Try different approach."
                        should_continue = True  # Force another iteration
                    else:
                        # Budget exhausted — suspend
                        await self._goal_engine.suspend_goal(
                            goal.id,
                            reason=f"Send-back budget exhausted ({max_sb} rounds)",
                        )
                        # IG-271: Autopilot suspending event removed, replaced with logging
                        logger.info(
                            "Goal %s suspending: Budget exhausted (%d rounds) - %s",
                            goal.id,
                            max_sb,
                            c_reasoning[:100],
                        )
                        async for chunk in self._save_checkpoint(
                            parent_state, user_input=user_input, mode="autonomous"
                        ):
                            yield chunk
                        return

                elif c_decision == "suspend":
                    await self._goal_engine.suspend_goal(
                        goal.id,
                        reason=f"Consensus suspension: {c_reasoning}",
                    )
                    async for chunk in self._save_checkpoint(
                        parent_state, user_input=user_input, mode="autonomous"
                    ):
                        yield chunk
                    return

                else:
                    # Accepted — mark as validated
                    await self._goal_engine.validate_goal(goal.id)
                    # IG-271: Autopilot validating event removed, replaced with logging
                    logger.debug("Goal %s validating: consensus check passed", goal.id)

            record = IterationRecord(
                iteration=total_iterations,
                goal_id=goal.id,
                plan_summary=plan_summary[:500],
                actions_summary=response_text[:500],
                reflection_assessment=reflection.assessment[:200] if reflection else "",
                outcome="continue" if should_continue else "goal_complete",
            )
            iteration_records.append(record)
            await self._store_iteration_record(record, canonical_tid)

            duration_ms = int((perf_counter() - iter_start) * 1000)
            # IG-271: Replace iteration event with compact logging
            logger.debug(
                "Iteration %d completed | Goal: %s | Outcome: %s | Duration: %dms",
                total_iterations,
                goal.id,
                record.outcome,
                duration_ms,
            )

            if not should_continue:
                goal_report = None
                if iter_state.plan:
                    from soothe.protocols.planner import (
                        GoalReport,
                    )
                    from soothe.protocols.planner import (
                        StepReport as StepReportModel,
                    )

                    sr_list = [
                        StepReportModel(
                            step_id=s.id,
                            description=s.description,
                            status=s.status if s.status in ("completed", "failed") else "skipped",
                            result=s.result or "",
                            depends_on=s.depends_on,
                        )
                        for s in iter_state.plan.steps
                        if s.status in ("completed", "failed", "pending")
                    ]
                    n_completed = sum(1 for r in sr_list if r.status == "completed")
                    n_failed = sum(1 for r in sr_list if r.status == "failed")

                    child_reports: list[Any] = []
                    if self._goal_engine:
                        for dep_id in getattr(goal, "depends_on", []):
                            dep_goal = self._goal_engine._goals.get(dep_id)
                            if dep_goal and dep_goal.report:
                                child_reports.append(dep_goal.report)

                    summary = await self._synthesize_root_goal_report(
                        goal,
                        sr_list,
                        child_reports,
                        max_chars=self._config.logging.report_output.synthesis_max_chars,
                    )

                    refl_assessment = ""
                    if reflection:
                        refl_assessment = reflection.assessment

                    goal_report = GoalReport(
                        goal_id=goal.id,
                        description=goal.description,
                        step_reports=sr_list,
                        summary=summary,
                        status="completed" if n_failed == 0 else "failed",
                        duration_ms=duration_ms,
                        reflection_assessment=refl_assessment,
                    )
                    goal.report = goal_report

                    logger.info(
                        "Goal %s report: %d/%d steps completed | Summary: %s",
                        goal.id,
                        n_completed,
                        len(sr_list),
                        goal_report.summary[:50],
                    )

                # RFC-204: Process proposals queued by Layer 2 tools before completing
                pq = getattr(self, "_proposal_queue", None)
                if pq is not None:
                    await self._process_proposals(goal.id, pq)

                await self._goal_engine.complete_goal(goal.id)

                # RFC-204: Detect relationships after goal completion
                rel_events = await self._detect_relationships_for_goal(goal)
                for ev in rel_events:
                    yield _custom(ev)

                parent_state.plan = iter_state.plan

                async for chunk in self._save_checkpoint(
                    parent_state, user_input=user_input, mode="autonomous"
                ):
                    yield chunk
                logger.debug("Post-goal checkpoint saved for goal %s", goal.id)

                logger.info("Goal %s completed", goal.id)

                # RFC-204: Webhook notification for goal completion
                await self._send_autopilot_webhook(
                    "goal_completed",
                    {
                        "goal_id": goal.id,
                        "description": goal.description[:200],
                        "status": "completed",
                        "summary": goal_report.summary[:200]
                        if goal_report and goal_report.summary
                        else "",
                    },
                )
            elif self._planner and iter_state.plan and reflection:
                try:
                    revised = await self._planner.revise_plan(iter_state.plan, reflection.feedback)
                    # Assign new plan ID for revision
                    goal.plan_count += 1
                    revised.id = f"P_{goal.plan_count}"

                    self._current_plan = revised
                    parent_state.plan = revised
                    parent_state.observation_refresh_needed = True
                except Exception:
                    logger.debug("Plan revision failed", exc_info=True)

            # IG-271: Replace iteration event with compact logging
            duration_ms = int((perf_counter() - iter_start) * 1000)
            outcome = (
                "completed" if not reflection or not reflection.should_revise else "needs_revision"
            )
            logger.debug(
                "Iteration %d completed | Goal: %s | Outcome: %s | Duration: %dms",
                total_iterations,
                goal.id,
                outcome,
                duration_ms,
            )

        except Exception as exc:
            logger.exception("Error during autonomous goal %s", goal.id)
            from soothe.utils.error_format import emit_error_event

            yield _custom(emit_error_event(exc, context="autonomous iteration"))

            updated = await self._goal_engine.fail_goal(goal.id, error=str(exc))
            yield _custom(
                GoalFailedEvent(
                    goal_id=goal.id,
                    error=str(exc),
                    retry_count=updated.retry_count,
                ).to_dict()
            )

            # RFC-204: Webhook notification for goal failure
            await self._send_autopilot_webhook(
                "goal_failed",
                {
                    "goal_id": goal.id,
                    "description": goal.description[:200],
                    "status": "failed",
                    "error": str(exc)[:500],
                },
            )

            # RFC-204: Process proposals even on failure (e.g., flag_blocker)
            pq = getattr(self, "_proposal_queue", None)
            if pq is not None:
                await self._process_proposals(goal.id, pq)

            if updated.status == "pending":
                backoff = _BACKOFF_BASE_SECONDS * (2 ** (updated.retry_count - 1))
                logger.info("Retrying goal %s after %.1fs backoff", goal.id, backoff)
                await asyncio.sleep(backoff)

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
        from soothe.cognition.goal_engine.criticality import evaluate_criticality_async

        description = proposal.payload.get("description", "")
        priority = proposal.payload.get("priority", 50)

        if not description:
            return

        result = await evaluate_criticality_async(
            description, priority, use_llm=True, model=getattr(self, "_model", None)
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
            from soothe.cognition.channel.models import ChannelMessage
            from soothe.cognition.channel.outbox import ChannelOutbox

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
            from soothe.cognition.goal_engine.webhooks import WebhookConfig, WebhookService

            webhook_url = None
            if self._config and hasattr(self._config, "autopilot"):
                webhook_url = self._config.autopilot.webhooks.get(f"on_{event_type}")

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
            from soothe.cognition.goal_engine.relationship_detector import (
                auto_apply_relationships,
                detect_relationships,
            )

            all_goals = await self._goal_engine.list_goals()
            relationships = detect_relationships(completed_goal, all_goals)
            if not relationships:
                return []

            # IG-271: Relationship detecting events removed, replaced with logging
            # Log relationships instead of emitting events
            for rel in relationships:
                logger.info(
                    "Relationship detected: %s %s %s (confidence=%.2f)",
                    rel.source_id,
                    rel.rel_type,
                    rel.target_id,
                    rel.confidence,
                )

            auto_apply_relationships(relationships, self._goal_engine)
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
            from soothe.cognition.scheduler import SchedulerService

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
            from soothe.cognition.goal_engine.dreaming import DreamingMode

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
