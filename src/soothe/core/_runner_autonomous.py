"""Autonomous iteration loop mixin for SootheRunner (RFC-0007, RFC-0009, RFC-0011).

Extracted from ``runner.py`` to isolate the autonomous goal-driven
execution logic from the main runner orchestration.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any

from soothe.core._runner_goal_directives import GoalDirectivesMixin
from soothe.core._runner_shared import _MIN_MEMORY_STORAGE_LENGTH, StreamChunk, _custom
from soothe.protocols.context import ContextEntry
from soothe.protocols.planner import PlanContext, StepResult

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
        max_iterations: int = 10,
    ) -> AsyncGenerator[StreamChunk]:
        """Autonomous iteration loop with DAG-based goal scheduling (RFC-0007, RFC-0009).

        Creates goals, executes plans via the step loop, reflects, revises,
        and iterates until goals are complete or max_iterations is reached.
        Independent goals can run in parallel with isolated threads.
        """
        import asyncio

        from soothe.core.runner import RunnerState

        if self._goal_engine is None:
            raise RuntimeError("Goal engine not initialized")

        state = RunnerState()
        state.thread_id = thread_id or self._current_thread_id or ""
        self._current_thread_id = state.thread_id or None

        # Perform unified classification for proper routing
        if self._unified_classifier:
            state.unified_classification = await self._unified_classifier.classify(user_input)
            logger.info(
                "Autonomous mode: unified classification task_complexity=%s - %s",
                state.unified_classification.task_complexity,
                user_input[:50],
            )

        # Fast path for chitchat - skip goal engine and planning
        if state.unified_classification and state.unified_classification.task_complexity == "chitchat":
            async for chunk in self._run_chitchat(user_input):
                yield chunk
            return

        async for chunk in self._pre_stream(user_input, state):
            yield chunk

        goal = await self._goal_engine.create_goal(user_input, priority=80)
        yield _custom(
            {
                "type": "soothe.goal.created",
                "goal_id": goal.id,
                "description": goal.description,
                "priority": goal.priority,
            }
        )

        from soothe.core.runner import IterationRecord

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
                    {
                        "type": "soothe.goal.batch_started",
                        "goal_ids": [g.id for g in ready_goals],
                        "parallel_count": len(ready_goals),
                    }
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
                            {"type": "soothe.goal.failed", "goal_id": g.id, "error": str(result), "retry_count": 0}
                        )
                    else:
                        for chunk in collected.get(g.id, []):
                            yield chunk
                total_iterations += len(ready_goals)

        # Emit final report for CLI (RFC-0010 / IG-027)
        root_report = getattr(goal, "report", None)
        if root_report and hasattr(root_report, "summary") and root_report.summary:
            yield _custom(
                {
                    "type": "soothe.autonomous.final_report",
                    "goal_id": goal.id,
                    "description": goal.description,
                    "status": root_report.status,
                    "summary": root_report.summary,
                }
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
            if self._artifact_store:
                self._artifact_store.update_status("completed")
            yield _custom({"type": "soothe.thread.saved", "thread_id": state.thread_id})
        except Exception:
            logger.debug("Final state persistence failed", exc_info=True)

        yield _custom({"type": "soothe.thread.ended", "thread_id": state.thread_id})

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

        from soothe.core.runner import IterationRecord, RunnerState

        yield _custom(
            {
                "type": "soothe.iteration.started",
                "iteration": total_iterations,
                "goal_id": goal.id,
                "goal_description": goal.description,
                "parallel_goals": parallel_goals,
            }
        )

        iter_start = perf_counter()
        current_input = goal.description

        try:
            iter_state = RunnerState()
            iter_state.thread_id = thread_id
            iter_state.unified_classification = parent_state.unified_classification

            if self._memory:
                try:
                    items = await self._memory.recall(current_input, limit=5)
                    iter_state.recalled_memories = items
                except Exception:
                    logger.debug("Memory recall failed", exc_info=True)

            if self._context:
                try:
                    projection = await self._context.project(current_input, token_budget=4000)
                    iter_state.context_projection = projection
                except Exception:
                    logger.debug("Context projection failed", exc_info=True)

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
                    )
                    plan = await self._planner.create_plan(current_input, context)
                    iter_state.plan = plan
                    self._current_plan = plan
                    yield _custom(
                        {
                            "type": "soothe.plan.created",
                            "goal": plan.goal,
                            "steps": [
                                {
                                    "id": s.id,
                                    "description": s.description,
                                    "status": s.status,
                                    "depends_on": s.depends_on,
                                }
                                for s in plan.steps
                            ],
                        }
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
                        MemoryItem(content=response_text[:500], tags=["agent_response"], source_thread=thread_id)
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
                        # Build goal context for reflection (RFC-0011)
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
                            {
                                "type": "soothe.plan.reflected",
                                "should_revise": reflection.should_revise,
                                "assessment": reflection.assessment[:200],
                            }
                        )

                        # Process goal directives from reflection (RFC-0011)
                        if reflection.goal_directives:
                            goal_changes = await self._process_goal_directives(
                                reflection.goal_directives,
                                current_goal=goal,
                            )

                            yield _custom(
                                {
                                    "type": "soothe.goal.directives_applied",
                                    "goal_id": goal.id,
                                    "directives_count": len(reflection.goal_directives),
                                    "changes": goal_changes,
                                }
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
                                    {
                                        "type": "soothe.goal.deferred",
                                        "goal_id": goal.id,
                                        "reason": "dependencies_added",
                                        "plan_preserved": iter_state.plan is not None,
                                    }
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
            record = IterationRecord(
                iteration=total_iterations,
                goal_id=goal.id,
                plan_summary=plan_summary[:500],
                actions_summary=response_text[:500],
                reflection_assessment=reflection.assessment[:200] if reflection else "",
                outcome="continue" if should_continue else "goal_complete",
            )
            iteration_records.append(record)
            await self._store_iteration_record(record, thread_id)

            duration_ms = int((perf_counter() - iter_start) * 1000)
            yield _custom(
                {
                    "type": "soothe.iteration.completed",
                    "iteration": total_iterations,
                    "goal_id": goal.id,
                    "outcome": record.outcome,
                    "duration_ms": duration_ms,
                }
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

                    summary = await self._synthesize_root_goal_report(goal, sr_list, child_reports)

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
                        {
                            "type": "soothe.goal.report",
                            "goal_id": goal.id,
                            "step_count": len(sr_list),
                            "completed": n_completed,
                            "failed": n_failed,
                            "summary": goal_report.summary[:200],
                        }
                    )

                if self._artifact_store and goal_report:
                    try:
                        self._artifact_store.write_goal_report(goal_report)
                        logger.debug("Goal report artifact written for %s", goal.id)
                    except Exception:
                        logger.debug("Goal report write failed", exc_info=True)

                await self._goal_engine.complete_goal(goal.id)

                parent_state.plan = iter_state.plan

                async for chunk in self._save_checkpoint(parent_state, user_input=user_input, mode="autonomous"):
                    yield chunk
                logger.debug("Post-goal checkpoint saved for goal %s", goal.id)

                yield _custom(
                    {
                        "type": "soothe.goal.completed",
                        "goal_id": goal.id,
                    }
                )
            elif self._planner and iter_state.plan and reflection:
                try:
                    revised = await self._planner.revise_plan(iter_state.plan, reflection.feedback)
                    self._current_plan = revised
                    parent_state.plan = revised
                except Exception:
                    logger.debug("Plan revision failed", exc_info=True)

        except Exception as exc:
            logger.exception("Error during autonomous goal %s", goal.id)
            from soothe.utils.error_format import emit_error_event

            yield _custom(emit_error_event(exc, context="autonomous iteration"))

            updated = await self._goal_engine.fail_goal(goal.id, error=str(exc))
            yield _custom(
                {
                    "type": "soothe.goal.failed",
                    "goal_id": goal.id,
                    "error": str(exc),
                    "retry_count": updated.retry_count,
                }
            )
            if updated.status == "pending":
                backoff = _BACKOFF_BASE_SECONDS * (2 ** (updated.retry_count - 1))
                logger.info("Retrying goal %s after %.1fs backoff", goal.id, backoff)
                await asyncio.sleep(backoff)
