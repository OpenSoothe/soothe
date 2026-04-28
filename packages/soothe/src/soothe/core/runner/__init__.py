"""SootheRunner -- protocol-orchestrated agent runner (RFC-0003, RFC-0007, RFC-0008, RFC-0009).

Wraps `create_soothe_agent()` with protocol pre/post-processing and
yields the deepagents-canonical ``(namespace, mode, data)`` stream
extended with ``soothe.*`` custom events for protocol observability.

RFC-0007 adds autonomous iteration: when ``autonomous=True``, the runner
loops reflect -> revise -> re-execute until the goal is complete or
max_iterations is reached.

RFC-0008 adds agentic loop: default execution mode with Reason → Act
iterative refinement loop (RFC-201) replacing single-pass execution.

RFC-0009 adds DAG-based step execution: plans with multiple steps are
iterated via ``StepScheduler``, independent steps can run in parallel,
and ``ConcurrencyController`` enforces hierarchical limits.

Implementation is decomposed into five mixins:

- `PhasesMixin`     -- pre/post-stream, LangGraph streaming, HITL loop
- `AgenticMixin`    -- agentic loop (RFC-0008)
- `AutonomousMixin` -- autonomous iteration loop (RFC-0007)
- `StepLoopMixin`   -- DAG-based step execution (RFC-0009)
- `CheckpointMixin` -- progressive checkpoint, artifacts, reports (RFC-0010)
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from soothe.config import SootheConfig
from soothe.core.workspace import resolve_workspace_for_stream
from soothe.protocols.planner import Plan, PlannerProtocol
from soothe.protocols.policy import PolicyProtocol

from ._runner_agentic import AgenticMixin
from ._runner_autonomous import AutonomousMixin
from ._runner_checkpoint import CheckpointMixin
from ._runner_phases import PhasesMixin
from ._runner_shared import StreamChunk
from ._runner_steps import StepLoopMixin
from ._types import IterationRecord, RunnerState, _generate_thread_id

# Re-export types
__all__ = [
    "IterationRecord",
    "RunnerState",
    "SootheRunner",
    "StreamChunk",
    "_generate_thread_id",
]

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.cognition import GoalEngine
    from soothe.core.agent import CoreAgent
    from soothe.protocols.memory import MemoryProtocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SootheRunner
# ---------------------------------------------------------------------------


class SootheRunner(CheckpointMixin, StepLoopMixin, AutonomousMixin, AgenticMixin, PhasesMixin):
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

        from soothe.cognition.intention import IntentClassifier
        from soothe.core.agent import create_soothe_agent
        from soothe.core.resolver import (
            resolve_checkpointer,
            resolve_durability,
            resolve_goal_engine,
        )
        from soothe.core.scheduling import ConcurrencyController

        init_start = time.perf_counter()

        self._config = config or SootheConfig()
        self._checkpointer_pool = None  # Will be set if using PostgreSQL

        # Initialize intent classifier (IG-226: cognition.intention module)
        if self._config.performance.enabled and self._config.performance.unified_classification:
            fast_model = None

            try:
                fast_model = self._config.create_chat_model("fast")
            except Exception:
                logger.exception(
                    "Failed to create fast model for classification. Classification will be disabled."
                )
                fast_model = None

            if fast_model:
                self._intent_classifier = IntentClassifier(
                    model=fast_model,
                    assistant_name=self._config.assistant_name,
                    config=self._config,  # IG-143: Pass config for LLM tracing
                )
                logger.info("[IntentClassifier] Initialized in LLM mode")
            else:
                logger.warning("No fast model available, classification disabled")
                self._intent_classifier = None
        else:
            self._intent_classifier = None

        checkpointer_start = time.perf_counter()
        checkpointer_result = resolve_checkpointer(self._config)
        if isinstance(checkpointer_result, tuple):
            self._checkpointer_pool = checkpointer_result[1]
            # Checkpointer will be created from pool in async context (_runner_phases.py)
            self._checkpointer = None  # Placeholder, set during async initialization
            self._checkpointer_initialized = False
        else:
            self._checkpointer = checkpointer_result
            self._checkpointer_pool = None
            self._checkpointer_initialized = True
        checkpointer_ms = (time.perf_counter() - checkpointer_start) * 1000
        logger.debug("Checkpointer resolved in %.1fms", checkpointer_ms)

        agent_start = time.perf_counter()
        self._agent: CoreAgent = create_soothe_agent(
            self._config,
            checkpointer=self._checkpointer,
        )
        agent_ms = (time.perf_counter() - agent_start) * 1000
        logger.info("CoreAgent created in %.1fms", agent_ms)

        # Access protocols via CoreAgent typed properties
        self._memory: MemoryProtocol | None = self._agent.memory
        self._planner: PlannerProtocol | None = self._agent.planner
        self._policy: PolicyProtocol | None = self._agent.policy

        # GoalEngine resolved in Layer 3 (separate from CoreAgent Layer 1)
        self._goal_engine: GoalEngine | None = resolve_goal_engine(self._config)

        durability_start = time.perf_counter()
        self._durability = resolve_durability(self._config)
        durability_ms = (time.perf_counter() - durability_start) * 1000
        logger.debug("Durability resolved in %.1fms", durability_ms)

        # Model for consensus loop (RFC-204 goal validation)
        self._model: Any | None = None
        try:
            self._model = self._config.create_chat_model("think")
            logger.debug("Consensus model initialized (role=think)")
        except Exception:
            logger.debug("Consensus model unavailable, consensus will use heuristic fallback")

        self._current_thread_id: str | None = None
        self._current_plan: Plan | None = None
        self._artifact_store: Any | None = (
            None  # Last-known store for CLI/debug; authoritative copy is on RunnerState
        )
        self._concurrency = ConcurrencyController(self._config.execution.concurrency)
        self._context_restore_lock = asyncio.Lock()
        self._interrupt_resolver: Any | None = None

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

    def _clear_query_scoped_runner_state(self) -> None:
        """Clear per-query mirrors on this singleton runner (IG-110).

        Authoritative plan and artifact data live on ``RunnerState`` per call;
        this resets CLI/debug pointers so cancelled or completed runs do not
        leak into the next ``astream`` invocation.
        """
        self._current_plan = None
        self._artifact_store = None

    def thread_context_manager(self) -> Any:
        """Return ``ThreadContextManager`` for durability/thread operations (IG-110).

        Callers outside core (e.g. daemon) should use this instead of reading
        ``runner._durability`` directly.
        """
        from soothe.core.thread import ThreadContextManager

        return ThreadContextManager(self._durability, self._config)

    async def resume_persisted_thread(self, thread_id: str) -> Any:
        """Resume thread metadata from durability (wrapper for daemon/CLI)."""
        return await self.thread_context_manager().resume_thread(thread_id)

    async def create_persisted_thread(
        self,
        *,
        thread_id: str | None = None,
        initial_message: Any = None,
        metadata: Any = None,
    ) -> Any:
        """Create a persisted thread (wrapper for daemon/CLI)."""
        return await self.thread_context_manager().create_thread(
            thread_id=thread_id,
            initial_message=initial_message,
            metadata=metadata,
        )

    async def list_persisted_threads(
        self,
        thread_filter: Any | None = None,
        *,
        include_stats: bool = False,
        include_last_message: bool = False,
    ) -> list[Any]:
        """List threads with optional filtering."""
        return await self.thread_context_manager().list_threads(
            thread_filter,
            include_stats=include_stats,
            include_last_message=include_last_message,
        )

    async def get_persisted_thread(self, thread_id: str) -> Any:
        """Return enhanced thread info."""
        return await self.thread_context_manager().get_thread(thread_id)

    async def archive_persisted_thread(self, thread_id: str) -> None:
        """Archive a thread."""
        await self.thread_context_manager().archive_thread(thread_id)

    async def delete_persisted_thread(self, thread_id: str) -> None:
        """Delete a thread."""
        await self.thread_context_manager().delete_thread(thread_id)

    async def get_persisted_thread_messages(
        self,
        thread_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        include_events: bool = False,
    ) -> list[Any]:
        """Load thread messages."""
        return await self.thread_context_manager().get_thread_messages(
            thread_id,
            limit=limit,
            offset=offset,
            include_events=include_events,
        )

    async def get_persisted_thread_artifacts(self, thread_id: str) -> list[Any]:
        """List thread artifacts."""
        return await self.thread_context_manager().get_thread_artifacts(thread_id)

    async def touch_thread_activity_timestamp(self, thread_id: str) -> None:
        """Refresh ``updated_at`` on thread metadata (activity ping)."""
        from datetime import UTC, datetime

        if not thread_id:
            return
        try:
            # IG-258 Phase 2: Use durability protocol methods instead of direct store access
            thread_info = await self._durability.get_thread(thread_id)
            thread_info = thread_info.model_copy(update={"updated_at": datetime.now(UTC)})
            await self._durability.update_thread_metadata(
                thread_id, thread_info.metadata.model_copy(update={"updated_at": datetime.now(UTC)})
            )
            logger.debug("Thread %s updated_at refreshed", thread_id)
        except Exception:
            logger.debug("touch_thread_activity_timestamp failed", exc_info=True)

    def protocol_summary(self) -> dict[str, str]:
        """Return a summary of active protocol implementations."""
        return {
            "memory": type(self._memory).__name__ if self._memory else "none",
            "planner": type(self._planner).__name__ if self._planner else "none",
            "policy": type(self._policy).__name__ if self._policy else "none",
            "durability": type(self._durability).__name__,
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

    async def list_durability_threads(self, thread_filter: Any | None = None) -> list[Any]:
        """List threads with optional ``ThreadFilter`` (daemon / tooling)."""
        return await self._durability.list_threads(thread_filter)

    async def cleanup(self) -> None:
        """Clean up resources during shutdown.

        Stops background indexer tasks and closes connection pools.
        """
        if self._checkpointer_pool is not None:
            try:
                # Check if pool is a string (SQLite path) or an object (PostgreSQL pool)
                is_sqlite = isinstance(self._checkpointer_pool, str)
            except Exception:
                is_sqlite = False

            try:
                if not is_sqlite:
                    # PostgreSQL pool needs explicit closing
                    await self._checkpointer_pool.close()
                    logger.info("Closed PostgreSQL checkpointer connection pool")
                # SQLite checkpointer manages its own connection via AsyncSqliteSaver
            except Exception:
                logger.debug("Failed to close checkpointer pool", exc_info=True)

        await self._close_attached_store(self._memory)

    def set_interrupt_resolver(self, resolver: Any | None) -> None:
        """Set a temporary interactive interrupt resolver for `_stream_phase`.

        Args:
            resolver: Async callable receiving pending interrupt payloads and
                returning a LangGraph resume payload, or `None` to restore the
                default auto-approve behavior.
        """
        self._interrupt_resolver = resolver

    async def get_thread_state_values(self, thread_id: str) -> dict[str, Any]:
        """Return checkpoint state values for a thread.

        Args:
            thread_id: Thread identifier to inspect.

        Returns:
            State values keyed by channel name. Empty when no checkpoint exists.
        """
        await self._ensure_checkpointer_initialized()
        config = {"configurable": {"thread_id": thread_id}}
        state = await self._agent.graph.aget_state(config)
        if state and state.values:
            return dict(state.values)
        return {}

    async def update_thread_state_values(self, thread_id: str, values: dict[str, Any]) -> None:
        """Persist partial checkpoint state for a thread.

        Args:
            thread_id: Thread identifier to update.
            values: Partial state values to write.
        """
        await self._ensure_checkpointer_initialized()
        config = {"configurable": {"thread_id": thread_id}}
        await self._agent.graph.aupdate_state(config, values)

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
            Tuple of (memory_items, None).
        """
        if complexity not in ("medium", "complex"):
            return ([], None)

        if self._memory:
            try:
                memory_items = await self._memory.recall(user_input, limit=5)
                return memory_items, None
            except Exception:
                logger.debug("Memory recall failed", exc_info=True)
                return ([], None)
        return ([], None)

    # -- main stream --------------------------------------------------------

    async def astream(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
        workspace: str | None = None,
        autonomous: bool = False,
        max_iterations: int | None = None,
        subagent: str | None = None,
    ) -> AsyncGenerator[StreamChunk]:
        """Stream agent execution with protocol orchestration.

        Yields ``(namespace, mode, data)`` tuples in the deepagents-canonical
        format.  Protocol events are emitted as ``custom`` events with
        ``soothe.*`` type prefix.

        **Two execution modes**:
        - ``autonomous=True`` (RFC-0007): Goal-driven iteration with explicit goal management
        - Default (RFC-201): Agentic loop with Reason → Act iteration

        **Quick path optimization**:
        - If `subagent` is provided, bypass classifier and route directly to subagent

        Args:
            user_input: The user's query text.
            thread_id: Thread ID for persistence. Generated if not provided.
            workspace: Thread-specific workspace path (RFC-103). When omitted, resolved via
                ``resolve_workspace_for_stream`` (config ``workspace_dir``, then cwd). The
                resolved path is always a non-empty absolute directory string for this call.
            autonomous: Enable autonomous iteration loop (explicit goals).
            max_iterations: Override max iterations from config.
            subagent: Optional subagent name to route the query to directly.
        """
        # Update thread_id for logging if one is provided
        from soothe.logging import set_thread_id

        # Only set thread_id if explicitly provided
        if thread_id:
            set_thread_id(thread_id)
        elif self._current_thread_id:
            set_thread_id(self._current_thread_id)

        resolved = resolve_workspace_for_stream(
            explicit=workspace,
            config_workspace_dir=getattr(self._config, "workspace_dir", None),
        )
        effective_workspace = resolved.path
        tid_for_log = str(thread_id or self._current_thread_id or "")
        logger.debug(
            "stream_workspace_resolved thread_id=%s path=%s source=%s",
            tid_for_log,
            effective_workspace,
            resolved.source,
        )

        try:
            # Quick path: direct subagent routing (bypasses classifier)
            if subagent:
                from ._types import RunnerState

                state = RunnerState()
                state.thread_id = str(thread_id or self._current_thread_id or "")
                state.workspace = effective_workspace

                # Load thread context for subagent (IG-140)
                await self._ensure_checkpointer_initialized()
                tid = str(thread_id or self._current_thread_id or "")
                recent_for_thread = await self._load_recent_messages(tid, limit=16)
                prior_limit = self._config.agentic.prior_conversation_limit if self._config else 10
                plan_excerpts = self._format_thread_messages_for_plan(
                    recent_for_thread, limit=prior_limit
                )

                # Pass context to subagent via state
                state.prior_messages = plan_excerpts

                logger.info(
                    "Quick path: routing directly to subagent '%s' with thread context", subagent
                )
                async for chunk in self._run_direct_subagent(user_input, subagent, state):
                    yield chunk
                return

            # Autonomous mode
            if autonomous and self._goal_engine:
                async for chunk in self._run_autonomous(
                    user_input,
                    thread_id=thread_id,
                    workspace=effective_workspace,
                    max_iterations=max_iterations or self._config.autonomous.max_iterations,
                ):
                    yield chunk
                return

            # Default: agentic loop (RFC-0008)
            async for chunk in self._run_agentic_loop(
                user_input,
                thread_id=thread_id,
                workspace=effective_workspace,
                max_iterations=max_iterations or self._config.agentic.max_iterations,
            ):
                yield chunk
        finally:
            self._clear_query_scoped_runner_state()
