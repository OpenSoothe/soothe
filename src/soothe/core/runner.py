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
from soothe.core._runner_steps import StepLoopMixin
from soothe.protocols.context import ContextProtocol
from soothe.protocols.planner import Plan, PlannerProtocol
from soothe.protocols.policy import PolicyProtocol

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langgraph.graph.state import CompiledStateGraph

    from soothe.core.goal_engine import GoalEngine
    from soothe.protocols.memory import MemoryProtocol

logger = logging.getLogger(__name__)

StreamChunk = tuple[tuple[str, ...], str, Any]
"""Deepagents-canonical stream chunk: ``(namespace, mode, data)``."""

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

        from soothe.core.agent import create_soothe_agent
        from soothe.core.concurrency import ConcurrencyController
        from soothe.core.resolver import resolve_checkpointer, resolve_durability
        from soothe.core.unified_classifier import UnifiedClassifier

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
        """
        if autonomous and self._goal_engine:
            async for chunk in self._run_autonomous(
                user_input,
                thread_id=thread_id,
                max_iterations=max_iterations or self._config.autonomous.max_iterations,
            ):
                yield chunk
            return

        async for chunk in self._run_single_pass(user_input, thread_id=thread_id):
            yield chunk

    async def _run_single_pass(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
    ) -> AsyncGenerator[StreamChunk]:
        """Single-pass execution with complexity-based routing.

        Routes based on unified classification:
        - chitchat: Fast path with direct LLM call, no planning, no state
        - medium: Normal flow with memory/context/planning
        - complex: Normal flow with memory/context/planning
        """
        state = RunnerState()
        state.thread_id = thread_id or self._current_thread_id or ""
        self._current_thread_id = state.thread_id or None

        # Early classification for chitchat routing
        if self._unified_classifier:
            state.unified_classification = await self._unified_classifier.classify(user_input)
            complexity = state.unified_classification.task_complexity
            logger.info(
                "Unified classification: task_complexity=%s, plan_only=%s - %s",
                state.unified_classification.task_complexity,
                state.unified_classification.is_plan_only,
                user_input[:50],
            )
        else:
            complexity = "medium"
            state.unified_classification = None

        # Fast path for chitchat
        if complexity == "chitchat":
            async for chunk in self._run_chitchat(user_input):
                yield chunk
            return

        # Normal path for medium/complex
        async for chunk in self._pre_stream(user_input, state):
            yield chunk

        # Use unified classification for plan-only detection (RFC-0012)
        is_plan_only = state.unified_classification and state.unified_classification.is_plan_only

        if state.plan and is_plan_only:
            yield _custom(
                {
                    "type": "soothe.plan.plan_only",
                    "thread_id": state.thread_id,
                    "goal": state.plan.goal,
                    "step_count": len(state.plan.steps),
                }
            )
        elif state.plan and len(state.plan.steps) > 1:
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
