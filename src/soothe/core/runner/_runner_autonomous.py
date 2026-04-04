"""Autonomous iteration loop mixin for SootheRunner (RFC-0007, RFC-0009).

Extracted from ``runner.py`` to isolate the autonomous goal-driven
execution logic from the main runner orchestration.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any

from soothe.core.event_catalog import (
    FinalReportEvent,
    GoalBatchStartedEvent,
    GoalCompletedEvent,
    GoalCreatedEvent,
    GoalDeferredEvent,
    GoalDirectivesAppliedEvent,
    GoalFailedEvent,
    GoalReportEvent,
    IterationCompletedEvent,
    IterationStartedEvent,
    PlanCreatedEvent,
    PlanReflectedEvent,
    ThreadEndedEvent,
    ThreadSavedEvent,
)
from soothe.protocols.context import ContextEntry
from soothe.protocols.planner import PlanContext, StepResult

from ._runner_goal_directives import GoalDirectivesMixin
from ._runner_shared import _MIN_MEMORY_STORAGE_LENGTH, StreamChunk, _custom, _validate_goal

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

_BACKOFF_BASE_SECONDS = 2.0


class AutonomousMixin(GoalDirectivesMixin):
    """Autonomous iteration loop (RFC-0007, RFC-0009).

    Mixed into ``SootheRunner`` -- all ``self.*`` attributes are defined
    on the concrete class.  Inherits goal directive processing from
    ``GoalDirectivesMixin``.
    """

    async def _run_autonomous(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
        workspace: str | None = None,
        max_iterations: int = 10,
    ) -> AsyncGenerator[StreamChunk]:
        """Autonomous iteration loop with DAG-based goal scheduling (RFC-0007, RFC-0009).

        Creates goals, executes plans via the step loop, reflects, revises,
        and iterates until goals are complete or max_iterations is reached.
        Independent goals can run in parallel with isolated threads.
        """
        import asyncio

        from ._types import RunnerState

        if self._goal_engine is None:
            raise RuntimeError("Goal engine not initialized")

        state = RunnerState()
        state.thread_id = thread_id or self._current_thread_id or ""
        state.workspace = workspace

        # Two-tier classification for proper routing
        if self._unified_classifier:
            from soothe.core.unified_classifier import UnifiedClassification

            routing = await self._unified_classifier.classify_routing(user_input)
            logger.info(
                "Autonomous mode: tier-1 routing task_complexity=%s - %s",
                routing.task_complexity,
                user_input[:50],
            )

            # Fast path for chitchat - skip goal engine and planning
            if routing.task_complexity == "chitchat":
                async for chunk in self._run_chitchat(user_input, classification=routing):
                    yield chunk
                return

            state.unified_classification = UnifiedClassification.from_routing(routing)
        else:
            state.unified_classification = None

        async for chunk in self._pre_stream_independent(user_input, state):
            yield chunk
        async for chunk in self._pre_stream_planning(user_input, state):
            yield chunk

        goal = await self._goal_engine.create_goal(user_input, priority=80)
        yield _custom(
            GoalCreatedEvent(
                goal_id=goal.id,
                description=goal.description,
                priority=goal.priority,
            ).to_dict()
        )

        from ._types import IterationRecord

        iteration_records: list[IterationRecord] = []
        total_iterations = 0

        while total_iterations < max_iterations and not self._goal_engine.is_complete():
            max_par_goals = self._concurrency.max_parallel_goals
            ready_goals = await self._goal_engine.ready_goals(limit=max_par_goals)
            if not ready_goals:
                logger.info("No more goals to process")
                break

            if len(ready_goals) > 1:
                yield _custom(
                    GoalBatchStartedEvent(
                        goal_ids=[g.id for g in ready_goals],
                        parallel_count=len(ready_goals),
                    ).to_dict()
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
                        yield _custom(
                            GoalFailedEvent(
                                goal_id=g.id,
                                error=str(result),
                                retry_count=0,
                            ).to_dict()
                        )
                    else:
                        for chunk in collected.get(g.id, []):
                            yield chunk
                total_iterations += len(ready_goals)

        # Emit final report for CLI (RFC-0010 / IG-027)
        root_report = getattr(goal, "report", None)
        if root_report and hasattr(root_report, "summary") and root_report.summary:
            yield _custom(
                FinalReportEvent(
                    goal_id=goal.id,
                    description=goal.description,
                    status=root_report.status,
                    summary=root_report.summary,
                ).to_dict()
            )

        try:
            if self._context and hasattr(self._context, "persist"):
                await self._context.persist(state.thread_id)
            async for chunk in self._save_checkpoint(
                state,
                user_input=user_input,
                mode="autonomous",
                status="completed",
            ):
                yield chunk
            if state.artifact_store:
                state.artifact_store.update_status("completed")
            yield _custom(ThreadSavedEvent(thread_id=state.thread_id).to_dict())
        except Exception:
            logger.debug("Final state persistence failed", exc_info=True)

        # RFC-204: Emit status change event
        yield _custom(
            {
                "type": "soothe.autopilot.status_changed",
                "state": "idle" if self._goal_engine.is_complete() else "running",
            }
        )

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
        """Execute a single goal in the autonomous loop (RFC-0009).

        Runs plan creation, step loop, reflection, and optional revision
        for one goal.  Each goal may use an isolated thread for parallel
        execution.
        """
        import asyncio

        from ._types import IterationRecord, RunnerState

        yield _custom(
            IterationStartedEvent(
                iteration=total_iterations,
                goal_id=goal.id,
                goal_description=goal.description,
                parallel_goals=parallel_goals,
            ).to_dict()
        )

        iter_start = perf_counter()
        current_input = goal.description

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
            iter_state.recalled_memories = list(getattr(parent_state, "recalled_memories", []) or [])
            iter_state.observation_scope_key = getattr(parent_state, "observation_scope_key", "")

            should_refresh_observation = getattr(parent_state, "observation_refresh_needed", False) or not (
                iter_state.context_projection is not None or iter_state.recalled_memories
            )

            if should_refresh_observation and self._memory:
                try:
                    items = await self._memory.recall(current_input, limit=5)
                    iter_state.recalled_memories = items
                except Exception:
                    logger.debug("Memory recall failed", exc_info=True)

            if should_refresh_observation and self._context:
                try:
                    projection = await self._context.project(current_input, token_budget=4000)
                    iter_state.context_projection = projection
                    iter_state.observation_scope_key = current_input
                except Exception:
                    logger.debug("Context projection failed", exc_info=True)

            parent_state.context_projection = iter_state.context_projection
            parent_state.recalled_memories = list(iter_state.recalled_memories)
            parent_state.observation_scope_key = iter_state.observation_scope_key
            parent_state.observation_refresh_needed = False

            # Reuse existing plan from parent_state if available (avoids duplicate plan creation)
            if parent_state and hasattr(parent_state, "plan") and parent_state.plan:
                iter_state.plan = parent_state.plan
                self._current_plan = iter_state.plan
                logger.info("Reusing existing plan with %d steps", len(iter_state.plan.steps))
            elif self._planner:
                # Only create new plan if none exists
                try:
                    capabilities = [name for name, cfg in self._config.subagents.items() if cfg.enabled]
                    completed = [
                        StepResult(step_id=r.goal_id, output=r.actions_summary[:200], success=r.outcome != "failed")
                        for r in iteration_records[-3:]
                    ]
                    context = PlanContext(
                        recent_messages=[current_input],
                        available_capabilities=capabilities,
                        completed_steps=completed,
                        unified_classification=parent_state.unified_classification,
                        workspace=parent_state.workspace if parent_state else None,
                        git_status=getattr(parent_state, "git_status", None) if parent_state else None,
                    )
                    plan = await self._planner.create_plan(current_input, context)
                    # Assign plan ID from goal counter
                    goal.plan_count += 1
                    plan.id = f"P_{goal.plan_count}"

                    iter_state.plan = plan
                    self._current_plan = plan
                    yield _custom(
                        PlanCreatedEvent(
                            plan_id=plan.id,
                            goal=_validate_goal(plan.goal, current_input),
                            steps=[
                                {
                                    "id": s.id,
                                    "description": s.description,
                                    "status": s.status,
                                    "depends_on": s.depends_on,
                                }
                                for s in plan.steps
                            ],
                            reasoning=plan.reasoning,
                            is_plan_only=plan.is_plan_only,
                        ).to_dict()
                    )
                except Exception:
                    logger.debug("Plan creation failed", exc_info=True)

            if iter_state.plan and len(iter_state.plan.steps) > 1:
                async for chunk in self._run_step_loop(current_input, iter_state, iter_state.plan, goal_id=goal.id):
                    yield chunk
            else:
                async with self._concurrency.acquire_llm_call():
                    async for chunk in self._stream_phase(current_input, iter_state):
                        yield chunk

            response_text = "".join(iter_state.full_response)
            if self._context and response_text:
                try:
                    await self._context.ingest(
                        ContextEntry(
                            source="agent",
                            content=response_text[:2000],
                            tags=["agent_response"],
                            importance=0.7,
                        )
                    )
                except Exception:
                    logger.debug("Context ingestion failed", exc_info=True)

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
                        StepResult(step_id=s.id, output=s.result or "", success=s.status == "completed")
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
                                completed_goals=[g.id for g in all_goals if g.status == "completed"],
                                failed_goals=[g.id for g in all_goals if g.status == "failed"],
                                ready_goals=[g.id for g in all_goals if g.status in ("pending", "active")],
                                max_parallel_goals=self._concurrency.max_parallel_goals,
                            )

                        reflection = await self._planner.reflect(iter_state.plan, step_results, goal_context)
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

                            yield _custom(
                                GoalDirectivesAppliedEvent(
                                    goal_id=goal.id,
                                    directives_count=len(reflection.goal_directives),
                                    changes=goal_changes,
                                ).to_dict()
                            )

                            # CRITICAL: Handle DAG state changes
                            # If the current goal now has unmet dependencies, reset it to pending
                            # and abort the current iteration
                            should_abort = await self._check_goal_dag_consistency(goal)

                            if should_abort:
                                logger.info("Goal %s now has unmet dependencies, resetting to pending", goal.id)
                                goal.status = "pending"
                                goal.updated_at = datetime.now(UTC)

                                # Note: The plan and any completed steps remain attached to this goal.
                                # When the goal is rescheduled after its dependencies complete,
                                # the planner can decide whether to create a new plan or revise the existing one.
                                # The existing plan provides context for the next iteration.

                                yield _custom(
                                    GoalDeferredEvent(
                                        goal_id=goal.id,
                                        reason="dependencies_added",
                                        plan_preserved=iter_state.plan is not None,
                                    ).to_dict()
                                )

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
                plan_summary = f"{iter_state.plan.goal}: " + "; ".join(s.description for s in iter_state.plan.steps[:5])

            should_continue = reflection.should_revise if reflection else False

            # RFC-204: Consensus loop — validate goal completion before accepting
            if self._goal_engine and self._model and not should_continue:
                from soothe.cognition.consensus import evaluate_goal_completion

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
                        current_input = (
                            f"Previous attempt did not satisfy goal. Feedback: {c_reasoning}. Try different approach."
                        )
                        should_continue = True  # Force another iteration
                    else:
                        # Budget exhausted — suspend
                        await self._goal_engine.suspend_goal(
                            goal.id,
                            reason=f"Send-back budget exhausted ({max_sb} rounds)",
                        )
                        yield _custom(
                            {
                                "type": "soothe.autopilot.goal_suspended",
                                "goal_id": goal.id,
                                "reason": f"Budget exhausted: {c_reasoning[:100]}",
                            }
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
                    async for chunk in self._save_checkpoint(parent_state, user_input=user_input, mode="autonomous"):
                        yield chunk
                    return

                else:
                    # Accepted — mark as validated
                    await self._goal_engine.validate_goal(goal.id)
                    yield _custom(
                        {
                            "type": "soothe.autopilot.goal_validated",
                            "goal_id": goal.id,
                            "confidence": 1.0,
                        }
                    )

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
            yield _custom(
                IterationCompletedEvent(
                    iteration=total_iterations,
                    goal_id=goal.id,
                    outcome=record.outcome,
                    duration_ms=duration_ms,
                ).to_dict()
            )

            if not should_continue:
                goal_report = None
                if iter_state.plan:
                    from soothe.protocols.planner import GoalReport, StepReport as StepReportModel

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

                    if self._context:
                        try:
                            await self._context.ingest(
                                ContextEntry(
                                    source="goal_report",
                                    content=f"[Goal {goal.id}] {goal_report.summary[:1000]}",
                                    tags=["goal_report", f"goal:{goal.id}"],
                                    importance=0.9,
                                )
                            )
                        except Exception:
                            logger.debug("Goal report ingestion failed", exc_info=True)

                    yield _custom(
                        GoalReportEvent(
                            goal_id=goal.id,
                            step_count=len(sr_list),
                            completed=n_completed,
                            failed=n_failed,
                            summary=goal_report.summary[:200],
                        ).to_dict()
                    )

                if iter_state.artifact_store and goal_report:
                    try:
                        iter_state.artifact_store.write_goal_report(goal_report)
                        logger.debug("Goal report artifact written for %s", goal.id)
                    except Exception:
                        logger.debug("Goal report write failed", exc_info=True)

                await self._goal_engine.complete_goal(goal.id)

                parent_state.plan = iter_state.plan

                async for chunk in self._save_checkpoint(parent_state, user_input=user_input, mode="autonomous"):
                    yield chunk
                logger.debug("Post-goal checkpoint saved for goal %s", goal.id)

                yield _custom(
                    GoalCompletedEvent(
                        goal_id=goal.id,
                    ).to_dict()
                )

                # RFC-204: Webhook notification for goal completion
                await self._send_autopilot_webhook(
                    "goal_completed",
                    {
                        "goal_id": goal.id,
                        "description": goal.description[:200],
                        "status": "completed",
                        "summary": goal_report.summary[:200] if goal_report and goal_report.summary else "",
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
                    entry = f"{payload.get('status', 'update')}: {payload.get('findings', '')[:200]}"
                    if self._goal_engine:
                        await self._goal_engine.append_goal_progress(goal_id, entry)

                elif proposal.type == "suggest_goal":
                    await self._handle_suggested_goal(proposal)

                elif proposal.type == "add_finding":
                    content = proposal.payload.get("content", "")
                    tags = proposal.payload.get("tags", [])
                    if self._context and content:
                        from soothe.protocols.context import ContextEntry

                        await self._context.ingest(
                            ContextEntry(
                                source="layer2_finding",
                                content=content[:1000],
                                tags=["finding", f"goal:{goal_id}", *tags],
                                importance=0.6,
                            )
                        )

                elif proposal.type == "flag_blocker":
                    reason = proposal.payload.get("reason", "Unknown blocker")
                    if self._goal_engine:
                        await self._goal_engine.block_goal(goal_id, reason=reason)
                    _custom(
                        {
                            "type": "soothe.autopilot.goal_blocked",
                            "goal_id": goal_id,
                            "reason": reason[:200],
                        }
                    )

            except Exception:
                logger.debug("Failed to process proposal: %s", proposal.type, exc_info=True)

    async def _handle_suggested_goal(self, proposal: Any) -> None:
        """RFC-204: Handle a suggested goal proposal with criticality check.

        If goal is evaluated as 'must', it queues for user confirmation.
        Otherwise it creates the goal immediately.

        Args:
            proposal: Proposal with type 'suggest_goal'.
        """
        from soothe.cognition.criticality import evaluate_criticality_async

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

    async def _queue_must_confirmation(self, description: str, priority: int, reasons: list[str]) -> None:
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
            from soothe.cognition.webhooks import WebhookConfig, WebhookService

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
            from soothe.cognition.dreaming import DreamingMode

            dreaming = DreamingMode(
                soothe_home=SOOTHE_HOME,
                memory_protocol=self._memory,
                context_protocol=self._context,
            )
            logger.info("Entering autopilot dreaming mode")

            # RFC-204: Emit dreaming events via WebSocket and webhook
            await self._send_autopilot_webhook("dreaming_entered", {})
            await dreaming.run()
            await self._send_autopilot_webhook("dreaming_exited", {})
        except Exception:
            logger.debug("Dreaming mode failed to start", exc_info=True)
