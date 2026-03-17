"""SootheRunner -- protocol-orchestrated agent runner (RFC-0003, RFC-0007, RFC-0009).

Wraps `create_soothe_agent()` with protocol pre/post-processing and
yields the deepagents-canonical ``(namespace, mode, data)`` stream
extended with ``soothe.*`` custom events for protocol observability.

RFC-0007 adds autonomous iteration: when ``autonomous=True``, the runner
loops reflect -> revise -> re-execute until the goal is complete or
max_iterations is reached.

RFC-0009 adds DAG-based step execution: plans with multiple steps are
iterated via ``StepScheduler``, independent steps can run in parallel,
and ``ConcurrencyController`` enforces hierarchical limits.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import HumanMessage
from langgraph.types import Command, Interrupt
from pydantic import BaseModel

from soothe.config import SootheConfig
from soothe.core.artifact_store import RunArtifactStore
from soothe.protocols.context import ContextEntry, ContextProjection, ContextProtocol
from soothe.protocols.planner import Plan, PlanContext, PlannerProtocol, PlanStep, StepResult
from soothe.protocols.policy import ActionRequest, PolicyContext, PolicyProtocol

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langgraph.graph.state import CompiledStateGraph

    from soothe.core.goal_engine import GoalEngine
    from soothe.protocols.memory import MemoryItem, MemoryProtocol

logger = logging.getLogger(__name__)

StreamChunk = tuple[tuple[str, ...], str, Any]
"""Deepagents-canonical stream chunk: ``(namespace, mode, data)``."""

_STREAM_CHUNK_LEN = 3
_MSG_PAIR_LEN = 2
_MAX_HITL_ITERATIONS = 50
_BACKOFF_BASE_SECONDS = 2.0
_MIN_MEMORY_STORAGE_LENGTH = 50


def _custom(data: dict[str, Any]) -> StreamChunk:
    """Build a soothe protocol custom event chunk."""
    return ((), "custom", data)


def _generate_thread_id() -> str:
    """Generate an 8-char hex thread ID (matching deepagents convention)."""
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Runner state
# ---------------------------------------------------------------------------


class IterationRecord(BaseModel):
    """Structured record of a single autonomous iteration (RFC-0007).

    Args:
        iteration: Zero-based iteration index.
        goal_id: Goal being worked on.
        plan_summary: Brief description of the plan at this iteration.
        actions_summary: Truncated agent response text.
        reflection_assessment: Planner's reflection assessment.
        outcome: Whether the iteration continues, completes, or fails.
    """

    iteration: int
    goal_id: str
    plan_summary: str
    actions_summary: str
    reflection_assessment: str
    outcome: Literal["continue", "goal_complete", "failed"]


@dataclass
class RunnerState:
    """Mutable state accumulated during a single query execution."""

    thread_id: str = ""
    full_response: list[str] = field(default_factory=list)
    plan: Plan | None = None
    context_projection: ContextProjection | None = None
    recalled_memories: list[MemoryItem] = field(default_factory=list)
    seen_message_ids: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# SootheRunner
# ---------------------------------------------------------------------------


class SootheRunner:
    """Protocol-orchestrated agent runner.

    Wraps ``create_soothe_agent()`` with pre/post protocol steps and
    provides ``astream()`` that yields the deepagents-canonical stream
    format extended with ``soothe.*`` protocol custom events.

    Args:
        config: Soothe configuration. If ``None``, uses defaults.
    """

    def __init__(self, config: SootheConfig | None = None) -> None:
        """Initialize the runner with optional config."""
        import time

        from soothe.core.agent import create_soothe_agent
        from soothe.core.concurrency import ConcurrencyController
        from soothe.core.query_classifier import QueryClassifier
        from soothe.core.resolver import resolve_checkpointer, resolve_durability

        init_start = time.perf_counter()

        self._config = config or SootheConfig()
        self._checkpointer_pool = None  # Will be set if using PostgreSQL

        # Initialize query classifier for performance optimization
        if self._config.performance.enabled and self._config.performance.complexity_detection:
            self._classifier = QueryClassifier(
                trivial_word_threshold=self._config.performance.thresholds.trivial_words,
                simple_word_threshold=self._config.performance.thresholds.simple_words,
                medium_word_threshold=self._config.performance.thresholds.medium_words,
            )
            logger.debug("Query classifier initialized")
        else:
            self._classifier = None

        checkpointer_start = time.perf_counter()
        checkpointer_result = resolve_checkpointer(self._config)
        # Handle both tuple (PostgreSQL with pool) and single checkpointer (MemorySaver)
        if isinstance(checkpointer_result, tuple):
            # PostgreSQL case: pool is available, checkpointer will be created in async context
            # Use MemorySaver temporarily during agent creation
            from langgraph.checkpoint.memory import MemorySaver

            self._checkpointer_pool = checkpointer_result[1]
            self._checkpointer = MemorySaver()  # Temporary checkpointer
            self._checkpointer_initialized = False
        else:
            self._checkpointer = checkpointer_result
            self._checkpointer_pool = None
            self._checkpointer_initialized = True
        checkpointer_ms = (time.perf_counter() - checkpointer_start) * 1000
        logger.debug("Checkpointer resolved in %.1fms", checkpointer_ms)

        agent_start = time.perf_counter()
        self._agent: CompiledStateGraph = create_soothe_agent(
            self._config,
            checkpointer=self._checkpointer,
        )
        agent_ms = (time.perf_counter() - agent_start) * 1000
        logger.info("Agent created in %.1fms", agent_ms)

        self._context: ContextProtocol | None = getattr(self._agent, "soothe_context", None)
        self._memory: MemoryProtocol | None = getattr(self._agent, "soothe_memory", None)
        self._planner: PlannerProtocol | None = getattr(self._agent, "soothe_planner", None)
        self._policy: PolicyProtocol | None = getattr(self._agent, "soothe_policy", None)
        self._goal_engine: GoalEngine | None = getattr(self._agent, "soothe_goal_engine", None)

        durability_start = time.perf_counter()
        self._durability = resolve_durability(self._config)
        durability_ms = (time.perf_counter() - durability_start) * 1000
        logger.debug("Durability resolved in %.1fms", durability_ms)

        self._current_thread_id: str | None = None
        self._current_plan: Plan | None = None
        self._artifact_store: RunArtifactStore | None = None
        self._concurrency = ConcurrencyController(self._config.execution.concurrency)

        total_ms = (time.perf_counter() - init_start) * 1000
        logger.info("SootheRunner initialized in %.1fms", total_ms)

    # -- public helpers -----------------------------------------------------

    @property
    def config(self) -> SootheConfig:
        """The active configuration."""
        return self._config

    @property
    def current_thread_id(self) -> str | None:
        """Thread ID for the active session, or ``None``."""
        return self._current_thread_id

    @property
    def current_plan(self) -> Plan | None:
        """The current plan, or ``None``."""
        return self._current_plan

    def set_current_thread_id(self, thread_id: str | None) -> None:
        """Set the active thread ID used by future runs.

        Args:
            thread_id: Thread ID to reuse, or ``None`` to clear.
        """
        self._current_thread_id = thread_id

    # -- checkpoint and artifact helpers (RFC-0010) --------------------------

    def _ensure_artifact_store(self, thread_id: str) -> RunArtifactStore:
        """Lazily create the artifact store when thread_id is known."""
        if self._artifact_store is None or self._artifact_store._thread_id != thread_id:
            self._artifact_store = RunArtifactStore(thread_id)
            logger.info("Artifact store initialized for thread %s", thread_id)
        return self._artifact_store

    async def _save_checkpoint(
        self,
        state: RunnerState,
        *,
        user_input: str,
        mode: str = "single_pass",
        status: str = "in_progress",
    ) -> AsyncGenerator[StreamChunk, None]:
        """Save progressive checkpoint for crash recovery (RFC-0010).

        Yields:
            soothe.checkpoint.saved stream event on successful save.
        """
        from datetime import UTC, datetime

        store = self._artifact_store
        if not store:
            return

        plan_data = state.plan.model_dump(mode="json") if state.plan else None
        completed = [s.id for s in (state.plan.steps if state.plan else []) if s.status == "completed"]
        goals_data = self._goal_engine.snapshot() if self._goal_engine else []

        envelope = {
            "version": 1,
            "timestamp": datetime.now(UTC).isoformat(),
            "mode": mode,
            "last_query": user_input,
            "thread_id": state.thread_id,
            "goals": goals_data,
            "active_goal_id": None,
            "plan": plan_data,
            "completed_step_ids": completed,
            "total_iterations": 0,
            "status": status,
        }
        try:
            store.save_checkpoint(envelope)
            logger.debug("Checkpoint saved: mode=%s status=%s completed=%d", mode, status, len(completed))
            # Emit stream event for observability (RFC-0010)
            yield _custom(
                {
                    "type": "soothe.checkpoint.saved",
                    "thread_id": state.thread_id,
                    "completed_steps": len(completed),
                    "completed_goals": len(goals_data),
                }
            )
        except Exception:
            logger.debug("Checkpoint save failed", exc_info=True)

    def _write_step_report_and_checkpoint(
        self,
        state: RunnerState,  # noqa: ARG002
        step: PlanStep,
        duration_ms: int,
        *,
        goal_id: str = "default",
    ) -> None:
        """Write step report to artifact store and save checkpoint.

        Called synchronously after step completion in the step loop.

        Args:
            state: Current runner state.
            step: The completed plan step.
            duration_ms: Step execution time in milliseconds.
            goal_id: Goal identifier for directory placement.
        """
        store = self._artifact_store
        if not store:
            return
        logger.debug(
            "Writing step report: goal=%s step=%s status=%s duration=%dms",
            goal_id,
            step.id,
            step.status,
            duration_ms,
        )
        try:
            store.write_step_report(
                goal_id=goal_id,
                step_id=step.id,
                description=step.description,
                status=step.status or "skipped",
                result=step.result or "",
                duration_ms=duration_ms,
                depends_on=step.depends_on,
            )
        except Exception:
            logger.debug("Step report write failed", exc_info=True)

    async def _try_recover_checkpoint(
        self,
        state: RunnerState,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Attempt to restore from a progressive checkpoint (RFC-0010).

        Loads checkpoint from ``RunArtifactStore``, restores goal engine
        and plan state, marks previously completed steps so
        ``StepScheduler`` will skip them.

        Args:
            state: Current runner state to populate with recovered data.

        Yields:
            Recovery stream events.
        """
        store = self._artifact_store
        if not store:
            return

        try:
            loaded = store.load_checkpoint()
        except Exception:
            logger.debug("Checkpoint load failed", exc_info=True)
            return

        if not loaded or not isinstance(loaded, dict):
            logger.debug("No checkpoint to recover for thread %s", state.thread_id)
            return
        cp_status = loaded.get("status")
        if cp_status != "in_progress":
            logger.debug("Checkpoint status is %s, skipping recovery", cp_status)
            return
        if loaded.get("version", 0) < 1:
            logger.debug("Checkpoint version too old, skipping recovery")
            return

        # Restore GoalEngine
        goals_data = loaded.get("goals", [])
        if goals_data and self._goal_engine:
            self._goal_engine.restore_from_snapshot(goals_data)
            logger.info("Recovered %d goals from checkpoint", len(goals_data))

        # Restore Plan with completed step status
        plan_data = loaded.get("plan")
        completed_ids = set(loaded.get("completed_step_ids", []))
        if plan_data:
            plan = Plan.model_validate(plan_data)
            for step in plan.steps:
                if step.id in completed_ids:
                    step.status = "completed"
            state.plan = plan
            self._current_plan = plan
            logger.info(
                "Recovered plan: %d/%d steps completed",
                len(completed_ids),
                len(plan.steps),
            )

        completed_goals = [g["id"] for g in goals_data if g.get("status") == "completed"]
        yield _custom(
            {
                "type": "soothe.recovery.resumed",
                "thread_id": state.thread_id,
                "completed_steps": list(completed_ids),
                "completed_goals": completed_goals,
                "mode": loaded.get("mode", "single_pass"),
            }
        )

    async def _synthesize_root_goal_report(
        self,
        goal: Any,
        step_reports: list[Any],
        child_goal_reports: list[Any],
    ) -> str:
        """Generate a cross-validated summary for a goal (RFC-0010).

        Uses an LLM call to synthesize findings from all steps and child
        goals, cross-checking for contradictions and gaps.  Falls back to
        a structured heuristic summary when the LLM is unavailable.

        Args:
            goal: The goal being summarized.
            step_reports: StepReport instances from this goal's plan.
            child_goal_reports: GoalReport instances from dependency goals.

        Returns:
            Synthesized summary string.
        """
        parts: list[str] = [f"Goal: {goal.description}\n"]

        if step_reports:
            parts.append("Step results:")
            for r in step_reports:
                icon = "+" if r.status == "completed" else "x"
                parts.append(f"  [{icon}] {r.step_id}: {r.description}\n      Result: {r.result[:2000]}")

        if child_goal_reports:
            parts.append("\nChild goal reports:")
            parts.extend(
                f"  Goal {cr.goal_id}: {cr.description}\n    Summary: {cr.summary[:500]}" for cr in child_goal_reports
            )

        synthesis_prompt = "\n".join(parts) + (
            "\n\n---\n"
            "Produce a comprehensive final report in Markdown for a human reader.\n"
            "Structure the report as follows:\n"
            "1. **Executive Summary**: 2-3 sentence overview of what was accomplished.\n"
            "2. **Key Findings**: Consolidate the most important data points, facts,\n"
            "   and conclusions from all steps into a coherent narrative. Use tables,\n"
            "   bullet points, or numbered lists where appropriate. Do NOT simply\n"
            "   repeat each step -- synthesize and deduplicate across steps.\n"
            "3. **Cross-Validation**: Note any contradictions, conflicting data, or\n"
            "   discrepancies found across steps. If none, state that sources agree.\n"
            "4. **Gaps & Limitations**: What information is missing or incomplete?\n"
            "5. **Confidence**: State high/medium/low based on source agreement.\n\n"
            "Keep the report between 500-2000 words. Write in the same language as\n"
            "the original goal. Use Markdown formatting for readability.\n"
        )

        try:
            if self._planner and hasattr(self._planner, "_invoke"):
                summary = await self._planner._invoke(synthesis_prompt)  # type: ignore[attr-defined]
                logger.info("LLM synthesis complete for goal %s (%d chars)", goal.id, len(summary))
                return summary[:8000]
        except Exception:
            logger.debug("LLM synthesis failed, using heuristic", exc_info=True)

        return self._heuristic_goal_summary(goal, step_reports)

    def _heuristic_goal_summary(self, goal: Any, step_reports: list[Any]) -> str:
        """Build a structured heuristic summary when LLM synthesis is unavailable.

        Concatenates step results into sections rather than a one-liner.

        Args:
            goal: The goal being summarized.
            step_reports: StepReport instances from this goal's plan.

        Returns:
            Markdown-formatted summary string.
        """
        completed = [r for r in step_reports if r.status == "completed"]
        failed = [r for r in step_reports if r.status == "failed"]
        logger.info(
            "Heuristic fallback for goal %s: %d completed, %d failed",
            goal.id, len(completed), len(failed),
        )

        lines: list[str] = []
        lines.append(f"# {goal.description}\n")
        lines.append(f"**Status**: {len(completed)}/{len(step_reports)} steps completed")
        if failed:
            lines.append(f"**Failed**: {', '.join(r.step_id for r in failed)}\n")
        else:
            lines.append("")

        for r in completed:
            lines.append(f"## {r.description}\n")
            result_text = r.result[:2000].strip() if r.result else "(no output)"
            lines.append(result_text)
            lines.append("")

        return "\n".join(lines)

    def protocol_summary(self) -> dict[str, str]:
        """Return a summary of active protocol implementations."""
        return {
            "context": type(self._context).__name__ if self._context else "none",
            "memory": type(self._memory).__name__ if self._memory else "none",
            "planner": type(self._planner).__name__ if self._planner else "none",
            "policy": type(self._policy).__name__ if self._policy else "none",
            "durability": type(self._durability).__name__,
        }

    async def context_stats(self) -> dict[str, Any]:
        """Return context statistics for the /context slash command."""
        if not self._context:
            return {"status": "disabled"}
        entries = getattr(self._context, "entries", [])
        return {
            "status": "active",
            "backend": type(self._context).__name__,
            "entries": len(entries) if isinstance(entries, list) else "unknown",
        }

    async def memory_stats(self) -> dict[str, Any]:
        """Return memory statistics for the /memory slash command."""
        if not self._memory:
            return {"status": "disabled"}
        return {
            "status": "active",
            "backend": type(self._memory).__name__,
        }

    async def list_threads(self) -> list[dict[str, Any]]:
        """List all threads via DurabilityProtocol."""
        threads = await self._durability.list_threads()
        return [t.model_dump() for t in threads]

    async def cleanup(self) -> None:
        """Clean up resources during shutdown.

        Stops background indexer tasks and closes connection pools.
        """
        # Close checkpointer connection pool if it exists
        if self._checkpointer_pool is not None:
            try:
                await self._checkpointer_pool.close()
                logger.info("Closed PostgreSQL checkpointer connection pool")
            except Exception:
                logger.debug("Failed to close checkpointer pool", exc_info=True)

        # Close context / memory backend stores when they expose async close().
        await self._close_attached_store(self._context)
        await self._close_attached_store(self._memory)

        # Stop subagent-owned resources.
        subagents = getattr(self._agent, "soothe_subagents", None) or getattr(self._agent, "subagents", [])
        for subagent in subagents:
            if not isinstance(subagent, dict):
                continue
            indexer = subagent.get("_skillify_indexer")
            if indexer is not None:
                try:
                    await indexer.stop()
                except Exception:
                    logger.debug("Failed to stop skillify indexer", exc_info=True)

            reuse_index = subagent.get("_weaver_reuse_index")
            if reuse_index is not None:
                await self._safe_close(reuse_index)

    async def _close_attached_store(self, owner: Any | None) -> None:
        """Close a nested `_store` field when available."""
        if owner is None:
            return
        store = getattr(owner, "_store", None)
        if store is not None:
            await self._safe_close(store)

    async def _safe_close(self, obj: Any) -> None:
        """Close an object that exposes a close method (sync or async)."""
        close_method = getattr(obj, "close", None)
        if not callable(close_method):
            return
        try:
            # Check if it's a coroutine function
            import asyncio

            if asyncio.iscoroutinefunction(close_method):
                await close_method()
            else:
                close_method()  # Call synchronously
        except Exception:
            logger.debug("Failed to close resource %s", type(obj).__name__, exc_info=True)

    # -- query classification helpers (RFC-0008) ----------------------------

    def _classify_query(self, query: str) -> str:
        """Classify query complexity for adaptive processing.

        Args:
            query: User input text.

        Returns:
            Complexity level: "trivial", "simple", "medium", or "complex".
        """
        if not self._classifier:
            # Classifier not enabled, default to medium (safe)
            return "medium"

        from soothe.core.query_classifier import ComplexityLevel

        level: ComplexityLevel = self._classifier.classify(query)
        return level

    def _get_template_plan(self, goal: str, complexity: str) -> Plan | None:
        """Get template plan for trivial/simple queries.

        Args:
            goal: The user's goal.
            complexity: Query complexity level.

        Returns:
            Template plan, or None if no template matches.
        """
        import re

        # Trivial: always single-step plan
        if complexity == "trivial":
            return Plan(
                goal=goal,
                steps=[PlanStep(id="step_1", description=goal, execution_hint="auto")],
            )

        # Simple: try to match common patterns
        goal_lower = goal.lower()

        # Search pattern
        if re.match(r"^(search|find|look up)\s+", goal_lower):
            return Plan(
                goal=goal,
                steps=[
                    PlanStep(id="step_1", description="Search for information", execution_hint="tool"),
                    PlanStep(id="step_2", description="Summarize findings", execution_hint="auto"),
                ],
            )

        # Analysis pattern
        if re.match(r"^(analyze|analyse|review|examine|investigate)\s+", goal_lower):
            return Plan(
                goal=goal,
                steps=[
                    PlanStep(id="step_1", description="Analyze the content", execution_hint="auto"),
                    PlanStep(id="step_2", description="Provide insights", execution_hint="auto"),
                ],
            )

        # Implementation pattern
        if re.match(r"^(implement|create|build|write|develop)\s+", goal_lower):
            return Plan(
                goal=goal,
                steps=[
                    PlanStep(id="step_1", description="Understand requirements", execution_hint="auto"),
                    PlanStep(id="step_2", description="Implement the solution", execution_hint="tool"),
                    PlanStep(id="step_3", description="Test and validate", execution_hint="tool"),
                ],
            )

        # Default simple plan
        return Plan(
            goal=goal,
            steps=[PlanStep(id="step_1", description=goal, execution_hint="auto")],
        )

    async def _pre_stream_parallel_memory_context(
        self,
        user_input: str,
        complexity: str,
    ) -> tuple[list[Any], Any | None]:
        """Run memory and context operations in parallel for medium/complex queries (RFC-0008 Phase 2).

        Args:
            user_input: User query text.
            complexity: Query complexity level.

        Returns:
            Tuple of (memory_items, context_projection).
        """
        import asyncio

        if complexity not in ("medium", "complex"):
            return ([], None)

        tasks = []

        # Memory recall task
        if self._memory:
            tasks.append(self._memory.recall(user_input, limit=5))
        else:
            tasks.append(asyncio.sleep(0, result=[]))

        # Context projection task
        if self._context:
            tasks.append(self._context.project(user_input, token_budget=4000))
        else:
            tasks.append(asyncio.sleep(0, result=None))

        # Execute in parallel
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            memory_items = [] if isinstance(results[0], Exception) else results[0]
            context_projection = None if isinstance(results[1], Exception) else results[1]

            if isinstance(results[0], Exception):
                logger.debug("Memory recall failed in parallel execution", exc_info=results[0])
            if isinstance(results[1], Exception):
                logger.debug("Context projection failed in parallel execution", exc_info=results[1])
        except Exception:
            logger.debug("Parallel execution failed", exc_info=True)
            return ([], None)
        else:
            return memory_items, context_projection

    # -- main stream --------------------------------------------------------

    async def astream(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
        autonomous: bool = False,
        max_iterations: int | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Stream agent execution with protocol orchestration.

        Yields ``(namespace, mode, data)`` tuples in the deepagents-canonical
        format.  Protocol events are emitted as ``custom`` events with
        ``soothe.*`` type prefix.

        When ``autonomous=True`` (RFC-0007), the runner loops: reflect ->
        revise -> re-execute until the goal is complete or ``max_iterations``
        is reached.

        Args:
            user_input: The user's query text.
            thread_id: Thread ID for persistence. Generated if not provided.
            autonomous: Enable autonomous iteration loop.
            max_iterations: Override ``autonomous_max_iterations`` from config.
        """
        if autonomous and self._goal_engine:
            async for chunk in self._run_autonomous(
                user_input,
                thread_id=thread_id,
                max_iterations=max_iterations or self._config.autonomous.max_iterations,
            ):
                yield chunk
            return

        # Default single-pass execution (unchanged)
        async for chunk in self._run_single_pass(user_input, thread_id=thread_id):
            yield chunk

    async def _run_single_pass(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Single-pass execution with DAG step loop (RFC-0009).

        Pre-stream creates the plan.  If the plan has multiple steps,
        the step loop drives execution via ``StepScheduler``.  Single-step
        plans fall through to a direct ``_stream_phase`` call for
        backward-compatible behavior.
        """
        state = RunnerState()
        state.thread_id = thread_id or self._current_thread_id or ""
        self._current_thread_id = state.thread_id or None

        async for chunk in self._pre_stream(user_input, state):
            yield chunk

        if state.plan and len(state.plan.steps) > 1:
            sp_goal_id = "default"
            if state.plan.goal:
                sp_goal_id = state.plan.goal[:32].replace(" ", "_").replace("/", "_")
            async for chunk in self._run_step_loop(user_input, state, state.plan, goal_id=sp_goal_id):
                yield chunk
        else:
            async with self._concurrency.acquire_llm_call():
                async for chunk in self._stream_phase(user_input, state):
                    yield chunk

        async for chunk in self._post_stream(user_input, state):
            yield chunk

    async def _run_autonomous(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
        max_iterations: int = 10,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Autonomous iteration loop with DAG-based goal scheduling (RFC-0007, RFC-0009).

        Creates goals, executes plans via the step loop, reflects, revises,
        and iterates until goals are complete or max_iterations is reached.
        Independent goals can run in parallel with isolated threads.
        """
        import asyncio

        if self._goal_engine is None:
            raise RuntimeError("Goal engine not initialized")

        state = RunnerState()
        state.thread_id = thread_id or self._current_thread_id or ""
        self._current_thread_id = state.thread_id or None

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

            # Execute goals (serial if 1, parallel if multiple)
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

        # Persist final state
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
        parent_state: RunnerState,
        thread_id: str,
        user_input: str,
        iteration_records: list[IterationRecord],
        total_iterations: int,
        parallel_goals: int = 1,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Execute a single goal in the autonomous loop (RFC-0009).

        Runs plan creation, step loop, reflection, and optional revision
        for one goal.  Each goal may use an isolated thread for parallel
        execution.
        """
        import asyncio

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

            # Plan creation
            if self._planner:
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

            # Step loop or single stream (RFC-0009)
            if iter_state.plan and len(iter_state.plan.steps) > 1:
                async for chunk in self._run_step_loop(current_input, iter_state, iter_state.plan, goal_id=goal.id):
                    yield chunk
            else:
                async with self._concurrency.acquire_llm_call():
                    async for chunk in self._stream_phase(current_input, iter_state):
                        yield chunk

            # Post-iteration: context ingestion, memory
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

            # Reflect
            reflection = None
            if self._planner and iter_state.plan and response_text:
                try:
                    step_results = [
                        StepResult(step_id=s.id, output=s.result or "", success=s.status == "completed")
                        for s in iter_state.plan.steps
                        if s.status in ("completed", "failed")
                    ]
                    if step_results:
                        reflection = await self._planner.reflect(iter_state.plan, step_results)
                        yield _custom(
                            {
                                "type": "soothe.plan.reflected",
                                "should_revise": reflection.should_revise,
                                "assessment": reflection.assessment[:200],
                            }
                        )
                except Exception:
                    logger.debug("Plan reflection failed", exc_info=True)

            # Journal
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
                # Assemble GoalReport from step results (RFC-0009, RFC-0010)
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

                    # Collect child goal reports for cross-validation (RFC-0010)
                    child_reports: list[GoalReport] = []
                    if self._goal_engine:
                        for dep_id in getattr(goal, "depends_on", []):
                            dep_goal = self._goal_engine._goals.get(dep_id)
                            if dep_goal and dep_goal.report:
                                child_reports.append(dep_goal.report)

                    # Synthesize summary with cross-validation (RFC-0010)
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
                    goal.report = goal_report  # RFC-0009: store structured object

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

                # Write goal report to artifact store (RFC-0010)
                if self._artifact_store and goal_report:
                    try:
                        self._artifact_store.write_goal_report(goal_report)
                        logger.debug("Goal report artifact written for %s", goal.id)
                    except Exception:
                        logger.debug("Goal report write failed", exc_info=True)

                await self._goal_engine.complete_goal(goal.id)

                # Propagate inner plan to parent so checkpoint captures step status
                parent_state.plan = iter_state.plan

                # Checkpoint after goal completion (RFC-0010)
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

    # -- step loop (RFC-0009) ------------------------------------------------

    async def _run_step_loop(
        self,
        goal_description: str,
        state: RunnerState,
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

        # Emit DAG snapshot for logs (RFC-0009 / IG-022)
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

            # Log batch execution info
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

            # Log parallel execution
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
                # Checkpoint after parallel batch (RFC-0010)
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
        state: RunnerState,  # noqa: ARG002
        batch_index: int = 0,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Execute a single plan step as a LangGraph invocation (RFC-0009).

        Builds step-specific input enriched with dependency results, runs
        the LangGraph agent, records the result, and ingests into context.
        """
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

        if response_text.strip():
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

    # -- stream + autonomous helpers ----------------------------------------

    async def _stream_phase(
        self,
        user_input: str,
        state: RunnerState,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Run the LangGraph stream with HITL interrupt loop."""
        enriched_messages = self._build_enriched_input(
            user_input,
            state.context_projection,
            state.recalled_memories,
        )
        stream_input: dict[str, Any] | Command = {"messages": enriched_messages}
        config = {"configurable": {"thread_id": state.thread_id}}

        # Initialize checkpointer pool if using AsyncPostgresSaver
        if not self._checkpointer_initialized and self._checkpointer_pool is not None:
            try:
                await self._checkpointer_pool.open()

                # Create the AsyncPostgresSaver now that we're in async context
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

                checkpointer = AsyncPostgresSaver(self._checkpointer_pool)
                await checkpointer.setup()

                # Replace the temporary MemorySaver with the real checkpointer
                self._checkpointer = checkpointer
                self._agent.checkpointer = checkpointer

                self._checkpointer_initialized = True
                logger.info("AsyncPostgresSaver pool opened and tables initialized, checkpointer replaced")
            except Exception as exc:
                logger.warning("Failed to initialize AsyncPostgresSaver: %s", exc)
                # Fall back to memory saver (already set)
                self._checkpointer_pool = None
                self._checkpointer_initialized = True
                logger.info("Using MemorySaver as fallback")

        hitl_iterations = 0
        while True:
            interrupt_occurred = False
            pending_interrupts: dict[str, Any] = {}

            try:
                async for chunk in self._agent.astream(
                    stream_input,
                    stream_mode=["messages", "updates", "custom"],
                    subgraphs=True,
                    config=config,
                ):
                    if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LEN:
                        continue

                    namespace, mode, data = chunk

                    if mode == "updates" and isinstance(data, dict) and "__interrupt__" in data:
                        interrupts: list[Interrupt] = data["__interrupt__"]
                        for interrupt_obj in interrupts:
                            pending_interrupts[interrupt_obj.id] = interrupt_obj.value
                            interrupt_occurred = True

                    if mode == "messages" and not namespace:
                        self._accumulate_response(data, state)

                    yield chunk

            except Exception as exc:
                logger.exception("Error during agent stream")
                from soothe.utils.error_format import emit_error_event

                yield _custom(emit_error_event(exc))
                # Don't break - let agent handle error and continue
                # Tools return error dicts/strings, so exceptions here are unexpected
                # but we shouldn't crash the entire conversation

            if not interrupt_occurred:
                break

            hitl_iterations += 1
            if hitl_iterations > _MAX_HITL_ITERATIONS:
                logger.warning("Exceeded HITL iteration limit (%d)", _MAX_HITL_ITERATIONS)
                from soothe.utils.error_format import emit_error_event

                yield _custom(emit_error_event(f"Exceeded {_MAX_HITL_ITERATIONS} HITL iterations"))
                break

            resume_payload = self._auto_approve(pending_interrupts)
            stream_input = Command(resume=resume_payload)

    async def _store_iteration_record(self, record: IterationRecord, _thread_id: str) -> None:
        """Persist an iteration record via ContextProtocol (RFC-0007)."""
        if not self._context:
            return
        try:
            await self._context.ingest(
                ContextEntry(
                    source="iteration_journal",
                    content=record.model_dump_json(),
                    tags=["iteration_record", f"iteration:{record.iteration}"],
                    importance=0.9,
                )
            )
        except Exception:
            logger.debug("Failed to store iteration record", exc_info=True)

    async def _synthesize_continuation(
        self,
        original_goal: str,
        records: list[IterationRecord],
        plan: Plan | None,
    ) -> str:
        """Generate the next iteration's input via a lightweight LLM call (RFC-0007)."""
        try:
            model = self._config.create_chat_model("fast")
        except Exception:
            try:
                model = self._config.create_chat_model("default")
            except Exception:
                logger.debug("Failed to create model for continuation synthesis")
                return original_goal

        history = "\n".join(f"- Iteration {r.iteration}: {r.reflection_assessment[:100]}" for r in records[-5:])
        plan_text = ""
        if plan:
            plan_text = f"\nRevised plan: {plan.goal}\nSteps: " + "; ".join(s.description for s in plan.steps[:5])

        prompt = (
            f"You are managing an autonomous agent. The original goal is:\n{original_goal}\n\n"
            f"History of iterations:\n{history}\n{plan_text}\n\n"
            "Generate a concise instruction for the next iteration. "
            "Focus on what specifically to do next based on what was learned. "
            "Do not repeat actions already completed."
        )

        try:
            response = await model.ainvoke([HumanMessage(content=prompt)])
            return str(response.content).strip() or original_goal
        except Exception:
            logger.debug("Continuation synthesis failed, reusing original goal", exc_info=True)
            return original_goal

    # -- phase helpers ------------------------------------------------------

    async def _pre_stream(
        self,
        user_input: str,
        state: RunnerState,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Run protocol pre-processing before the LangGraph stream."""
        from soothe.protocols.durability import ThreadMetadata

        # Query complexity classification (RFC-0008)
        complexity = "medium"  # Default to existing behavior
        if self._config.performance.enabled and self._config.performance.complexity_detection:
            complexity = self._classify_query(user_input)
            logger.info("Query classified as: %s (%s)", complexity, user_input[:50])

        # Thread management
        requested_thread_id = state.thread_id
        try:
            thread_info = None
            if requested_thread_id:
                thread_info = await self._durability.resume_thread(requested_thread_id)
                yield _custom({"type": "soothe.thread.resumed", "thread_id": thread_info.thread_id})
            else:
                thread_info = await self._durability.create_thread(
                    ThreadMetadata(policy_profile=self._config.protocols.policy.profile),
                )
                yield _custom({"type": "soothe.thread.created", "thread_id": thread_info.thread_id})
            state.thread_id = thread_info.thread_id
            self._current_thread_id = thread_info.thread_id
        except KeyError:
            logger.debug("Thread resume failed, creating a new thread", exc_info=True)
            try:
                thread_info = await self._durability.create_thread(
                    ThreadMetadata(policy_profile=self._config.protocols.policy.profile),
                )
                yield _custom({"type": "soothe.thread.created", "thread_id": thread_info.thread_id})
                state.thread_id = thread_info.thread_id
                self._current_thread_id = thread_info.thread_id
            except Exception:
                logger.debug("Thread creation failed after resume fallback", exc_info=True)
        except Exception:
            logger.debug("Thread creation failed, using generated ID", exc_info=True)

        if not state.thread_id:
            state.thread_id = requested_thread_id or _generate_thread_id()
            self._current_thread_id = state.thread_id

        # Initialize artifact store (RFC-0010)
        store = self._ensure_artifact_store(state.thread_id)
        if store and not store.manifest.query:
            store._manifest.query = user_input[:200]
            store.save_manifest()

        # Context restoration (when resuming a thread)
        if self._context and hasattr(self._context, "restore") and requested_thread_id:
            try:
                restored = await self._context.restore(state.thread_id)
                if restored:
                    logger.info("Context restored for thread %s", state.thread_id)
            except Exception:
                logger.debug("Context restore failed", exc_info=True)

        # Crash recovery (RFC-0010)
        if requested_thread_id:
            async for chunk in self._try_recover_checkpoint(state):
                yield chunk

        protocols = self.protocol_summary()
        yield _custom(
            {
                "type": "soothe.thread.started",
                "thread_id": state.thread_id,
                "protocols": protocols,
            }
        )

        # Policy check
        if self._policy:
            try:
                from soothe.protocols.policy import PermissionSet

                decision = self._policy.check(
                    ActionRequest(action_type="user_request", tool_name=None, tool_args={}),
                    PolicyContext(
                        active_permissions=PermissionSet(frozenset()),
                        thread_id=state.thread_id,
                    ),
                )
                yield _custom(
                    {
                        "type": "soothe.policy.checked",
                        "action": "user_request",
                        "verdict": decision.verdict,
                        "profile": self._config.protocols.policy.profile,
                    }
                )
                if decision.verdict == "deny":
                    yield _custom(
                        {
                            "type": "soothe.policy.denied",
                            "action": "user_request",
                            "reason": decision.reason,
                            "profile": self._config.protocols.policy.profile,
                        }
                    )
                    return
            except Exception:
                logger.debug("Policy check failed", exc_info=True)

        # Memory recall and context projection - CONDITIONAL + PARALLEL (RFC-0008)
        should_run_memory_context = (
            not self._config.performance.enabled
            or not self._config.performance.skip_memory_for_simple
            or complexity in ("medium", "complex")
        )

        if should_run_memory_context:
            # Use parallel execution if enabled
            if self._config.performance.enabled and self._config.performance.parallel_pre_stream:
                memory_items, context_projection = await self._pre_stream_parallel_memory_context(
                    user_input, complexity
                )

                state.recalled_memories = memory_items
                state.context_projection = context_projection

                # Ingest memory into context
                if self._context and memory_items:
                    for item in memory_items:
                        try:
                            await self._context.ingest(
                                ContextEntry(
                                    source="memory",
                                    content=item.content[:2000],
                                    tags=["recalled_memory", *item.tags],
                                    importance=item.importance,
                                )
                            )
                        except Exception:
                            logger.debug("Memory ingestion failed", exc_info=True)

                # Emit events
                if memory_items:
                    yield _custom(
                        {
                            "type": "soothe.memory.recalled",
                            "count": len(memory_items),
                            "query": user_input[:100],
                        }
                    )
                if context_projection:
                    yield _custom(
                        {
                            "type": "soothe.context.projected",
                            "entries": context_projection.total_entries,
                            "tokens": context_projection.token_count,
                        }
                    )
            else:
                # Sequential execution (Phase 1 or disabled)
                # Memory recall
                if self._memory:
                    try:
                        items = await self._memory.recall(user_input, limit=5)
                        state.recalled_memories = items
                        if self._context and items:
                            for item in items:
                                await self._context.ingest(
                                    ContextEntry(
                                        source="memory",
                                        content=item.content[:2000],
                                        tags=["recalled_memory", *item.tags],
                                        importance=item.importance,
                                    )
                                )
                        yield _custom(
                            {
                                "type": "soothe.memory.recalled",
                                "count": len(items),
                                "query": user_input[:100],
                            }
                        )
                    except Exception:
                        logger.debug("Memory recall failed", exc_info=True)

                # Context projection
                if self._context:
                    try:
                        projection = await self._context.project(user_input, token_budget=4000)
                        state.context_projection = projection
                        yield _custom(
                            {
                                "type": "soothe.context.projected",
                                "entries": projection.total_entries,
                                "tokens": projection.token_count,
                            }
                        )
                    except Exception:
                        logger.debug("Context projection failed", exc_info=True)

        # Plan creation - ADAPTIVE (RFC-0008)
        if self._planner:
            try:
                capabilities = [name for name, cfg in self._config.subagents.items() if cfg.enabled]
                context = PlanContext(
                    recent_messages=[user_input],
                    available_capabilities=capabilities,
                    completed_steps=[],
                )

                # Use template for trivial/simple queries
                if (
                    self._config.performance.enabled
                    and self._config.performance.template_planning
                    and complexity in ("trivial", "simple")
                ):
                    plan = self._get_template_plan(user_input, complexity)
                    logger.info("Using template plan for %s query", complexity)
                else:
                    # Fall back to LLM planning
                    plan = await self._planner.create_plan(user_input, context)

                state.plan = plan
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
                if plan.steps:
                    yield _custom(
                        {
                            "type": "soothe.plan.step_started",
                            "index": 0,
                            "description": plan.steps[0].description,
                        }
                    )
            except Exception:
                logger.debug("Plan creation failed", exc_info=True)

    async def _post_stream(
        self,
        user_input: str,
        state: RunnerState,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Run protocol post-processing after the LangGraph stream."""
        response_text = "".join(state.full_response)

        # Context ingestion
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
                yield _custom(
                    {
                        "type": "soothe.context.ingested",
                        "source": "agent",
                        "content_preview": response_text[:80],
                    }
                )
            except Exception:
                logger.debug("Context ingestion failed", exc_info=True)

        # Context persistence
        if self._context and hasattr(self._context, "persist"):
            try:
                await self._context.persist(state.thread_id)
            except Exception:
                logger.debug("Context persistence failed", exc_info=True)

        # Memory storage for significant responses
        if self._memory and response_text and len(response_text) > _MIN_MEMORY_STORAGE_LENGTH:
            try:
                from soothe.protocols.memory import MemoryItem

                await self._memory.remember(
                    MemoryItem(
                        content=response_text[:500],
                        tags=["agent_response"],
                        source_thread=state.thread_id,
                    )
                )
                yield _custom(
                    {
                        "type": "soothe.memory.stored",
                        "id": "auto",
                        "source_thread": state.thread_id,
                    }
                )
            except Exception:
                logger.debug("Memory storage failed", exc_info=True)

        # Plan reflection (RFC-0009: reflect on ALL steps, not just steps[0])
        if self._planner and state.plan:
            try:
                # For single-step plans that went through _stream_phase directly,
                # update step[0] status from the response.
                if state.plan.steps and state.plan.steps[0].status == "pending" and response_text:
                    first_step_success = bool(response_text.strip())
                    state.plan.steps[0].status = "completed" if first_step_success else "failed"
                    state.plan.steps[0].result = response_text[:200] if first_step_success else None
                    yield _custom(
                        {
                            "type": "soothe.plan.step_completed",
                            "step_id": state.plan.steps[0].id,
                            "success": first_step_success,
                            "duration_ms": 0,
                        }
                    )

                step_results = [
                    StepResult(step_id=s.id, output=s.result or "", success=s.status == "completed")
                    for s in state.plan.steps
                    if s.status in ("completed", "failed")
                ]
                if step_results:
                    reflection = await self._planner.reflect(state.plan, step_results)
                    yield _custom(
                        {
                            "type": "soothe.plan.reflected",
                            "should_revise": reflection.should_revise,
                            "assessment": reflection.assessment[:200],
                        }
                    )
            except Exception:
                logger.debug("Plan reflection failed", exc_info=True)

        # State persistence (RFC-0010: via RunArtifactStore)
        try:
            async for chunk in self._save_checkpoint(
                state,
                user_input=user_input,
                mode="single_pass",
                status="completed",
            ):
                yield chunk
            if self._artifact_store:
                self._artifact_store.update_status("completed")
            yield _custom({"type": "soothe.thread.saved", "thread_id": state.thread_id})
        except Exception:
            logger.debug("State persistence failed", exc_info=True)

        yield _custom({"type": "soothe.thread.ended", "thread_id": state.thread_id})

    # -- internal helpers ---------------------------------------------------

    def _build_enriched_input(
        self,
        user_input: str,
        projection: ContextProjection | None,
        memories: list[MemoryItem],
    ) -> list[HumanMessage]:
        """Build the enriched input messages with context and memories."""
        parts: list[str] = []

        if projection and projection.entries:
            context_text = "\n".join(f"- [{e.source}] {e.content[:200]}" for e in projection.entries[:10])
            parts.append(f"<context>\n{context_text}\n</context>")

        if memories:
            memory_text = "\n".join(f"- [{m.source_thread or 'unknown'}] {m.content[:200]}" for m in memories[:5])
            parts.append(f"<memory>\n{memory_text}\n</memory>")

        enriched = "\n\n".join(parts) + f"\n\n{user_input}" if parts else user_input

        return [HumanMessage(content=enriched)]

    def _accumulate_response(self, data: Any, state: RunnerState) -> None:
        """Extract AI text from a messages-mode chunk."""
        from langchain_core.messages import AIMessage, AIMessageChunk

        if not isinstance(data, tuple) or len(data) != _MSG_PAIR_LEN:
            return
        msg, metadata = data
        if metadata and metadata.get("lc_source") == "summarization":
            return
        if not isinstance(msg, AIMessage):
            return

        msg_id = msg.id or ""
        if not isinstance(msg, AIMessageChunk):
            if msg_id in state.seen_message_ids:
                return
            state.seen_message_ids.add(msg_id)
        elif msg_id:
            state.seen_message_ids.add(msg_id)

        if hasattr(msg, "content_blocks") and msg.content_blocks:
            for block in msg.content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        state.full_response.append(text)
        elif isinstance(msg.content, str) and msg.content:
            state.full_response.append(msg.content)

    @staticmethod
    def _auto_approve(pending_interrupts: dict[str, Any]) -> dict[str, Any]:
        """Auto-approve all HITL interrupts."""
        payload: dict[str, Any] = {}
        for iid, value in pending_interrupts.items():
            if isinstance(value, dict) and value.get("type") == "ask_user":
                questions = value.get("questions", [])
                payload[iid] = {"answers": ["" for _ in questions]}
            else:
                action_requests = []
                if isinstance(value, dict):
                    action_requests = value.get("action_requests", [])
                decisions = [{"type": "approve"} for _ in (action_requests or [value])]
                payload[iid] = {"decisions": decisions}
        return payload
