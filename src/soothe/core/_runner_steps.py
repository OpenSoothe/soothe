"""DAG-based step execution mixin for SootheRunner (RFC-0009).

Extracted from ``runner.py`` to isolate the step scheduling and
execution loop from the main runner orchestration.
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import TYPE_CHECKING, Any

from soothe.protocols.context import ContextEntry
from soothe.protocols.planner import Plan, PlanStep

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

StreamChunk = tuple[tuple[str, ...], str, Any]


def _custom(data: dict[str, Any]) -> StreamChunk:
    """Build a soothe protocol custom event chunk."""
    return ((), "custom", data)


class StepLoopMixin:
    """DAG-based step execution (RFC-0009).

    Mixed into ``SootheRunner`` -- all ``self.*`` attributes are defined
    on the concrete class.
    """

    async def _run_step_loop(
        self,
        goal_description: str,
        state: Any,
        plan: Plan,
        *,
        goal_id: str = "default",
    ) -> AsyncGenerator[StreamChunk, None]:
        """Execute plan steps respecting DAG dependencies (RFC-0009).

        Iterates through batches of ready steps.  Sequential steps reuse
        the main thread; parallel steps get isolated thread IDs.

        Args:
            goal_description: Human-readable goal text.
            state: Current runner state.
            plan: Plan to execute.
            goal_id: Goal identifier for artifact store directory placement.
        """
        import asyncio

        from soothe.core.step_scheduler import StepScheduler

        scheduler = StepScheduler(plan)
        parallelism = self._concurrency.step_parallelism

        if len(plan.steps) > 1 and any(s.depends_on for s in plan.steps):
            dep_count = sum(1 for s in plan.steps if s.depends_on)
            logger.info("Plan DAG: %d steps, %d with dependencies", len(plan.steps), dep_count)
            yield _custom(
                {
                    "type": "soothe.plan.dag_snapshot",
                    "steps": [{"id": s.id, "depends_on": s.depends_on} for s in plan.steps],
                }
            )
        max_steps = self._concurrency.max_parallel_steps
        batch_index = 0

        while not scheduler.is_complete():
            ready = scheduler.ready_steps(limit=max_steps, parallelism=parallelism)
            if not ready:
                logger.warning("No ready steps but scheduler not complete -- breaking")
                break

            step_ids = [s.id for s in ready]
            if len(ready) == 1:
                logger.info("Batch %d: 1 step ready (%s)", batch_index, step_ids[0])
            else:
                logger.info("Batch %d: %d steps ready %s", batch_index, len(ready), step_ids)

            yield _custom(
                {
                    "type": "soothe.plan.batch_started",
                    "batch_index": batch_index,
                    "step_ids": [s.id for s in ready],
                    "parallel_count": len(ready),
                }
            )

            for s in ready:
                scheduler.mark_in_progress(s.id)

            if len(ready) > 1:
                logger.info("Executing %d steps in parallel", len(ready))

            if len(ready) == 1:
                step = ready[0]
                dep_results = scheduler.get_dependency_results(step)
                step_start = perf_counter()
                async for chunk in self._execute_step(
                    step,
                    goal_description=goal_description,
                    dependency_results=dep_results,
                    thread_id=state.thread_id,
                    state=state,
                    batch_index=batch_index,
                ):
                    yield chunk
                step_dur = int((perf_counter() - step_start) * 1000)
                if step.status == "completed":
                    scheduler.mark_completed(step.id, step.result or "")
                elif step.status != "failed":
                    scheduler.mark_failed(step.id, step.result or "No result")
                self._write_step_report_and_checkpoint(state, step, step_dur, goal_id=goal_id)
            else:
                collected_chunks: dict[str, list[StreamChunk]] = {}

                async def _run_one(
                    s: PlanStep,
                    _collected: dict[str, list[StreamChunk]] = collected_chunks,
                    _batch: int = batch_index,
                ) -> None:
                    chunks: list[StreamChunk] = []
                    dep_results = scheduler.get_dependency_results(s)
                    step_tid = f"{state.thread_id}__step_{s.id}"
                    async with self._concurrency.acquire_step():
                        async for chunk in self._execute_step(
                            s,
                            goal_description=goal_description,
                            dependency_results=dep_results,
                            thread_id=step_tid,
                            state=state,
                            batch_index=_batch,
                        ):
                            chunks.append(chunk)  # noqa: PERF401
                    _collected[s.id] = chunks

                results = await asyncio.gather(
                    *[_run_one(s) for s in ready],
                    return_exceptions=True,
                )
                for s, result in zip(ready, results, strict=True):
                    if isinstance(result, Exception):
                        scheduler.mark_failed(s.id, str(result))
                        yield _custom(
                            {
                                "type": "soothe.plan.step_failed",
                                "step_id": s.id,
                                "error": str(result),
                            }
                        )
                    else:
                        for chunk in collected_chunks.get(s.id, []):
                            yield chunk
                        if s.status == "completed":
                            scheduler.mark_completed(s.id, s.result or "")
                        elif s.status != "failed":
                            scheduler.mark_failed(s.id, s.result or "No result")
                for s in ready:
                    self._write_step_report_and_checkpoint(state, s, 0, goal_id=goal_id)

            batch_index += 1

        state.full_response = [s.result or "" for s in plan.steps if s.status == "completed"]

    async def _execute_step(
        self,
        step: PlanStep,
        *,
        goal_description: str,
        dependency_results: list[tuple[str, str]],
        thread_id: str,
        state: Any,  # noqa: ARG002
        batch_index: int = 0,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Execute a single plan step as a LangGraph invocation (RFC-0009).

        Builds step-specific input enriched with dependency results, runs
        the LangGraph agent, records the result, and ingests into context.
        """
        from soothe.core.runner import RunnerState

        step_start = perf_counter()

        parts = [f"Goal: {goal_description}", f"Current step: {step.description}"]
        if dependency_results:
            dep_text = "\n".join(f"- [{desc}]: {result[:300]}" for desc, result in dependency_results)
            parts.append(f"Results from prior steps:\n{dep_text}")
        step_input = "\n\n".join(parts)

        yield _custom(
            {
                "type": "soothe.plan.step_started",
                "step_id": step.id,
                "description": step.description,
                "depends_on": step.depends_on,
                "batch_index": batch_index,
            }
        )

        step_state = RunnerState()
        step_state.thread_id = thread_id

        if self._memory:
            try:
                items = await self._memory.recall(step.description, limit=3)
                step_state.recalled_memories = items
            except Exception:
                logger.debug("Memory recall failed for step %s", step.id, exc_info=True)

        if self._context:
            try:
                projection = await self._context.project(step.description, token_budget=3000)
                step_state.context_projection = projection
            except Exception:
                logger.debug("Context projection failed for step %s", step.id, exc_info=True)

        async with self._concurrency.acquire_llm_call():
            async for chunk in self._stream_phase(step_input, step_state):
                yield chunk

        response_text = "".join(step_state.full_response)
        duration_ms = int((perf_counter() - step_start) * 1000)

        if step_state.stream_error:
            step.status = "failed"
            step.result = f"Stream error: {step_state.stream_error}"
            blocked = [
                s.id
                for s in (self._current_plan.steps if self._current_plan else [])
                if step.id in s.depends_on and s.status == "pending"
            ]
            yield _custom(
                {
                    "type": "soothe.plan.step_failed",
                    "step_id": step.id,
                    "error": step.result,
                    "blocked_steps": blocked,
                    "duration_ms": duration_ms,
                }
            )
        elif response_text.strip():
            step.status = "completed"
            step.result = response_text[:2000]
            yield _custom(
                {
                    "type": "soothe.plan.step_completed",
                    "step_id": step.id,
                    "success": True,
                    "result_preview": response_text[:200],
                    "duration_ms": duration_ms,
                }
            )
        else:
            step.status = "failed"
            step.result = "No response from agent"
            blocked = [
                s.id
                for s in (self._current_plan.steps if self._current_plan else [])
                if step.id in s.depends_on and s.status == "pending"
            ]
            yield _custom(
                {
                    "type": "soothe.plan.step_failed",
                    "step_id": step.id,
                    "error": "No response from agent",
                    "blocked_steps": blocked,
                }
            )

        if self._context and step.result:
            try:
                await self._context.ingest(
                    ContextEntry(
                        source="step_result",
                        content=f"[Step {step.id}: {step.description}]\n{step.result[:1500]}",
                        tags=["step_result", f"step:{step.id}"],
                        importance=0.85,
                    )
                )
            except Exception:
                logger.debug("Step result ingestion failed", exc_info=True)
