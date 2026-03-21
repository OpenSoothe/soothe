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

Implementation is decomposed into four mixins:

- `PhasesMixin`     -- pre/post-stream, LangGraph streaming, HITL loop
- `AutonomousMixin` -- autonomous iteration loop (RFC-0007)
- `StepLoopMixin`   -- DAG-based step execution (RFC-0009)
- `CheckpointMixin` -- progressive checkpoint, artifacts, reports (RFC-0010)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from soothe.config import SootheConfig
from soothe.core._runner_autonomous import AutonomousMixin
from soothe.core._runner_checkpoint import CheckpointMixin
from soothe.core._runner_phases import PhasesMixin
from soothe.core._runner_shared import StreamChunk, _custom
from soothe.core._runner_steps import StepLoopMixin
from soothe.core.event_catalog import FinalReportEvent, PlanOnlyEvent
from soothe.protocols.context import ContextProtocol
from soothe.protocols.planner import Plan, PlannerProtocol
from soothe.protocols.policy import PolicyProtocol

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langgraph.graph.state import CompiledStateGraph

    from soothe.cognition import GoalEngine
    from soothe.protocols.memory import MemoryProtocol

logger = logging.getLogger(__name__)


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
    context_projection: Any = None
    recalled_memories: list[Any] = field(default_factory=list)
    seen_message_ids: set[str] = field(default_factory=set)
    stream_error: str | None = None
    unified_classification: Any = None  # Type: UnifiedClassification


# ---------------------------------------------------------------------------
# SootheRunner
# ---------------------------------------------------------------------------


class SootheRunner(CheckpointMixin, StepLoopMixin, AutonomousMixin, PhasesMixin):
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

        from soothe.cognition import UnifiedClassifier
        from soothe.core.agent import create_soothe_agent
        from soothe.core.concurrency import ConcurrencyController
        from soothe.core.resolver import resolve_checkpointer, resolve_durability

        init_start = time.perf_counter()

        self._config = config or SootheConfig()
        self._checkpointer_pool = None  # Will be set if using PostgreSQL

        # Initialize unified classifier (RFC-0012)
        if self._config.performance.enabled and self._config.performance.unified_classification:
            fast_model = None

            try:
                fast_model = self._config.create_chat_model("fast")
            except Exception:
                logger.exception("Failed to create fast model for classification. Classification will be disabled.")
                fast_model = None

            if fast_model:
                self._unified_classifier = UnifiedClassifier(
                    fast_model=fast_model,
                    classification_mode=self._config.performance.classification_mode,
                    assistant_name=self._config.assistant_name,
                )
                logger.info("Unified classifier initialized in %s mode", self._config.performance.classification_mode)
            else:
                logger.warning("No fast model available, classification disabled")
                self._unified_classifier = None
        else:
            self._unified_classifier = None

        checkpointer_start = time.perf_counter()
        checkpointer_result = resolve_checkpointer(self._config)
        if isinstance(checkpointer_result, tuple):
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
        self._artifact_store: Any | None = None
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
        if self._checkpointer_pool is not None:
            try:
                await self._checkpointer_pool.close()
                logger.info("Closed PostgreSQL checkpointer connection pool")
            except Exception:
                logger.debug("Failed to close checkpointer pool", exc_info=True)

        await self._close_attached_store(self._context)
        await self._close_attached_store(self._memory)

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
            import asyncio

            if asyncio.iscoroutinefunction(close_method):
                await close_method()
            else:
                close_method()
        except Exception:
            logger.debug("Failed to close resource %s", type(obj).__name__, exc_info=True)

    # -- query classification helpers (RFC-0008, RFC-0012) -----------------

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

        if self._memory:
            tasks.append(self._memory.recall(user_input, limit=5))
        else:
            tasks.append(asyncio.sleep(0, result=[]))

        if self._context:
            tasks.append(self._context.project(user_input, token_budget=4000))
        else:
            tasks.append(asyncio.sleep(0, result=None))

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
        subagent: str | None = None,
    ) -> AsyncGenerator[StreamChunk]:
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
            subagent: Optional subagent name to route the query to directly.
        """
        if autonomous and self._goal_engine:
            async for chunk in self._run_autonomous(
                user_input,
                thread_id=thread_id,
                max_iterations=max_iterations or self._config.autonomous.max_iterations,
            ):
                yield chunk
            return

        async for chunk in self._run_single_pass(user_input, thread_id=thread_id, subagent=subagent):
            yield chunk

    async def _run_single_pass(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
        subagent: str | None = None,
    ) -> AsyncGenerator[StreamChunk]:
        """Single-pass execution with two-tier classification.

        Tier-1 (fast routing) decides chitchat vs. non-chitchat immediately.
        For non-chitchat, tier-2 enrichment runs concurrently with the
        independent pre-stream work (thread/policy/memory/context).

        Args:
            user_input: The user's query text.
            thread_id: Thread ID for persistence. Generated if not provided.
            subagent: Optional subagent name to route the query to directly.
        """
        import asyncio

        from soothe.cognition import UnifiedClassification

        state = RunnerState()
        state.thread_id = thread_id or self._current_thread_id or ""
        self._current_thread_id = state.thread_id or None

        # If subagent is explicitly specified, bypass classification and route directly
        if subagent:
            async for chunk in self._run_direct_subagent(user_input, subagent, state):
                yield chunk
            return

        # -- Tier 1: fast routing (~2-4s) -----------------------------------
        if self._unified_classifier:
            routing = await self._unified_classifier.classify_routing(user_input)
            complexity = routing.task_complexity
            logger.info("Tier-1 routing: task_complexity=%s - %s", complexity, user_input[:50])
        else:
            routing = None
            complexity = "medium"

        # Fast path for chitchat (no planning, no state)
        if complexity == "chitchat":
            async for chunk in self._run_chitchat(user_input, classification=routing):
                yield chunk
            return

        # -- Non-chitchat: planning + pre-stream independent -------
        # Start planning concurrently with I/O
        from soothe.protocols.planner import Plan, PlanContext, PlanStep

        planning_task = asyncio.create_task(
            self._planner.create_plan(
                user_input,
                PlanContext(
                    recent_messages=[user_input],
                    available_capabilities=[name for name, cfg in self._config.subagents.items() if cfg.enabled],
                    completed_steps=[],
                    unified_classification=routing,  # Pass routing directly
                ),
            )
        )

        # Run independent pre-stream (thread, policy, memory, context)
        # concurrently with planning.
        collected_chunks = [
            chunk async for chunk in self._pre_stream_independent(user_input, state, complexity=complexity)
        ]

        # Await planning
        try:
            plan = await planning_task
            state.plan = plan
            self._current_plan = plan
            state.unified_classification = UnifiedClassification.from_routing(routing)
            logger.info(
                "Unified planning completed: %d steps, plan_only=%s - %s",
                len(plan.steps),
                plan.is_plan_only,
                user_input[:50],
            )
        except Exception:
            logger.exception("Planning failed")
            # Fallback to single-step plan
            plan = Plan(
                goal=user_input,
                steps=[PlanStep(id="step_1", description=user_input)],
                is_plan_only=False,
            )
            state.plan = plan
            state.unified_classification = UnifiedClassification.from_routing(routing)

        # Yield all collected independent pre-stream events
        for chunk in collected_chunks:
            yield chunk

        # -- Planning phase (emit plan created event) -----------------------
        if state.plan:
            from soothe.cli.rendering.events import PlanCreatedEvent

            yield _custom(
                PlanCreatedEvent(
                    goal=state.plan.goal,
                    steps=[{"id": s.id, "description": s.description} for s in state.plan.steps],
                ).to_dict()
            )

        # -- Execute ---------------------------------------------------------
        is_plan_only = state.plan and state.plan.is_plan_only

        if state.plan and is_plan_only:
            yield _custom(
                PlanOnlyEvent(
                    thread_id=state.thread_id,
                    goal=state.plan.goal,
                    step_count=len(state.plan.steps),
                ).to_dict()
            )
        elif state.plan and len(state.plan.steps) > 1:
            sp_goal_id = "default"
            if state.plan.goal:
                sp_goal_id = state.plan.goal[:32].replace(" ", "_").replace("/", "_")
            async for chunk in self._run_step_loop(user_input, state, state.plan, goal_id=sp_goal_id):
                yield chunk

            async for chunk in self._synthesize_single_pass_report(state):
                yield chunk
        else:
            async with self._concurrency.acquire_llm_call():
                async for chunk in self._stream_phase(user_input, state):
                    yield chunk

        async for chunk in self._post_stream(user_input, state):
            yield chunk

    async def _synthesize_single_pass_report(
        self,
        state: RunnerState,
    ) -> AsyncGenerator[StreamChunk]:
        """Synthesize a final report after a multi-step single-pass run.

        Mirrors the autonomous path's report synthesis so the headless CLI
        can display a consolidated report to the user.

        Args:
            state: Current runner state with completed plan.
        """
        from types import SimpleNamespace

        from soothe.protocols.planner import StepReport as StepReportModel

        plan = state.plan
        if not plan or len(plan.steps) <= 1:
            return

        sr_list = [
            StepReportModel(
                step_id=s.id,
                description=s.description,
                status=s.status if s.status in ("completed", "failed") else "skipped",
                result=s.result or "",
                depends_on=s.depends_on,
            )
            for s in plan.steps
            if s.status in ("completed", "failed", "pending")
        ]

        n_completed = sum(1 for r in sr_list if r.status == "completed")
        if n_completed == 0:
            return

        goal_obj = SimpleNamespace(
            id=state.thread_id or "default",
            description=plan.goal or "User request",
        )

        try:
            summary = await self._synthesize_root_goal_report(goal_obj, sr_list, [])
        except Exception:
            logger.debug("Single-pass report synthesis failed", exc_info=True)
            return

        if summary:
            yield _custom(
                FinalReportEvent(
                    goal_id=goal_obj.id,
                    description=goal_obj.description,
                    status="completed" if all(r.status == "completed" for r in sr_list) else "partial",
                    summary=summary,
                ).to_dict()
            )
