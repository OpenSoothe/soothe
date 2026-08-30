"""SootheRunner: protocol-orchestrated agent runner."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe_sdk.protocols.planner import Plan, PlannerProtocol
from soothe_sdk.protocols.policy import PolicyProtocol

from soothe.config import SootheConfig
from soothe.workspace import resolve_workspace_for_stream

from ._runner_phases import PhasesMixin
from ._runner_shared import StreamChunk
from ._runner_strange_loop import StrangeLoopMixin
from ._types import generate_thread_id

# Re-export types
__all__ = [
    "SootheRunner",
    "generate_thread_id",
]

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe_sdk.protocols.core_agent import CoreAgentProtocol
    from soothe_sdk.protocols.memory import MemoryProtocol

    from soothe.coreagent.lazy import LazyCoreAgent
    from soothe.identity.runtime import IdentityRuntime

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SootheRunner
# ---------------------------------------------------------------------------


class SootheRunner(
    StrangeLoopMixin,
    PhasesMixin,
):
    """Protocol-orchestrated agent runner wrapping `create_soothe_agent()`."""

    def __init__(
        self,
        config: SootheConfig | None = None,
        *,
        identity_runtime: IdentityRuntime | None = None,
    ) -> None:
        """Initialize the runner with optional config."""
        import time

        from soothe.coreagent import create_soothe_agent
        from soothe.coreagent.lazy import LazyCoreAgent
        from soothe.runner.resolver import (
            resolve_checkpointer,
            resolve_durability,
            resolve_planner,
            resolve_policy,
        )
        from soothe.sloop.intention.classifier import IntentClassifier

        init_start = time.perf_counter()

        self._config = config or SootheConfig()
        self._identity_runtime = identity_runtime
        self._checkpointer_pool = None  # Will be set if using PostgreSQL

        # Apply configurable persona identity to nano's module-level fragment
        # so the runtime SystemPromptMiddleware hot path renders the configured
        # creator/role/vendor denylist. No-op when all fields are defaults.
        from soothe.identity.persona import apply_identity_fragment_override

        apply_identity_fragment_override(self._config)

        # Initialize intent classifier (core.intention module).
        # Unified classification is always enabled; classifier is omitted only if fast model is unavailable.
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
                assistant_name=self._config.agent.name,
                soothe_config=self._config,
                assistant_identity=self._config.agent.assistant_identity,
            )
            logger.info("[IntentClassifier] Initialized in LLM mode")
        else:
            logger.warning("No fast model available, classification disabled")
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

        self._planner: PlannerProtocol | None = resolve_planner(self._config, None)
        self._policy: PolicyProtocol | None = resolve_policy(self._config)
        self._memory: MemoryProtocol | None = None

        lazy_core_agent = self._config.agent.runtime.lazy_core_agent

        def _build_core_agent() -> CoreAgentProtocol:
            agent_start = time.perf_counter()
            agent = create_soothe_agent(
                self._config,
                checkpointer=self._checkpointer,
                identity_runtime=self._identity_runtime,
            )
            agent_ms = (time.perf_counter() - agent_start) * 1000
            logger.info("CoreAgent created in %.1fms", agent_ms)
            self._memory = agent.memory
            if self._planner is None:
                self._planner = agent.planner
            if self._policy is None:
                self._policy = agent.policy
            return agent

        if lazy_core_agent:
            self._core_agent: CoreAgentProtocol | LazyCoreAgent = LazyCoreAgent(
                _build_core_agent,
                planner=self._planner,
                policy=self._policy,
                config=self._config,
                materialize_hook=lambda _agent: self._ensure_checkpointer_initialized(),
            )
            logger.info("[Init] LazyCoreAgent configured")
        else:
            self._core_agent = _build_core_agent()

        # Read-only "ask" graph, compiled lazily on the first ask turn (IG-758).
        # Shares ``self._checkpointer`` with the default agent so thread state
        # carries across mode switches within a conversation.
        self._ask_core_agent: CoreAgentProtocol | None = None
        # Read-only "plan" graph, compiled lazily on the first plan turn.
        # Same read-only constraints as ask, but with a plan-specific system prompt
        # and empty subagent allowlist.
        self._plan_core_agent: CoreAgentProtocol | None = None

        durability_start = time.perf_counter()
        self._durability = resolve_durability(self._config)
        durability_ms = (time.perf_counter() - durability_start) * 1000
        logger.debug("Durability resolved in %.1fms", durability_ms)

        self._current_thread_id: str | None = None
        self._current_plan: Plan | None = None
        # Client-visible loop id for the active ``astream`` (daemon loop scope / logging).
        self._client_loop_id_for_stream: str | None = None
        # Live StrangeLoop instance for the active goal (hot-swap target).
        self._live_loop_agent: Any = None

        # Shared PostgreSQL pool for StrangeLoop state persistence
        # Initialized lazily in async context for high-concurrency support
        self._sloop_shared_pool: Any = None  # SharedPostgreSQLPool | None

        total_ms = (time.perf_counter() - init_start) * 1000
        logger.info("SootheRunner initialized in %.1fms", total_ms)

    @property
    def _agent(self) -> CoreAgentProtocol | LazyCoreAgent:
        """Agent handle for the active stream (lazy or materialized)."""
        return self._core_agent

    async def _materialize_core_agent(
        self, interaction_mode: str | None = None
    ) -> CoreAgentProtocol:
        """Ensure the CoreAgent graph for `interaction_mode` is compiled.

        `"ask"` selects the read-only graph; anything else (including
        `None`) selects the default graph. The checkpointer is attached
        before an ask graph is compiled so both graphs share one checkpointer.
        """
        from soothe.coreagent.lazy import LazyCoreAgent

        if interaction_mode == "ask":
            return await self._materialize_ask_core_agent()
        if interaction_mode == "plan":
            return await self._materialize_plan_core_agent()
        if isinstance(self._core_agent, LazyCoreAgent):
            return await self._core_agent.amaterialize()
        await self._ensure_checkpointer_initialized()
        return self._core_agent

    async def _materialize_ask_core_agent(self) -> CoreAgentProtocol:
        """Compile (once) and return the read-only `interaction_mode="ask"` agent."""
        if self._ask_core_agent is None:
            # The checkpointer may be created lazily from a pool; ensure it
            # exists before compiling so the ask graph shares it with the
            # default agent (thread continuity across mode switches).
            await self._ensure_checkpointer_initialized()
            import time

            from soothe.coreagent import create_soothe_agent

            agent_start = time.perf_counter()
            self._ask_core_agent = create_soothe_agent(
                self._config,
                checkpointer=self._checkpointer,
                identity_runtime=self._identity_runtime,
                interaction_mode="ask",
            )
            agent_ms = (time.perf_counter() - agent_start) * 1000
            logger.info("CoreAgent (ask) created in %.1fms", agent_ms)
        return self._ask_core_agent

    async def _materialize_plan_core_agent(self) -> CoreAgentProtocol:
        """Compile (once) and return the read-only `interaction_mode="plan"` agent."""
        if self._plan_core_agent is None:
            await self._ensure_checkpointer_initialized()
            import time

            from soothe.coreagent import create_soothe_agent

            agent_start = time.perf_counter()
            self._plan_core_agent = create_soothe_agent(
                self._config,
                checkpointer=self._checkpointer,
                identity_runtime=self._identity_runtime,
                interaction_mode="plan",
            )
            agent_ms = (time.perf_counter() - agent_start) * 1000
            logger.info("CoreAgent (plan) created in %.1fms", agent_ms)
        return self._plan_core_agent

    def _materialized_core_agent(self) -> CoreAgentProtocol:
        """Return a compiled CoreAgent, materializing lazily when needed."""
        from soothe.coreagent.lazy import LazyCoreAgent

        if isinstance(self._core_agent, LazyCoreAgent):
            return self._core_agent.materialize()
        return self._core_agent

    def prepare_for_request(self) -> None:
        """Reset per-request runner mirrors without recompiling CoreAgent."""
        self._clear_query_scoped_runner_state()
        self._client_loop_id_for_stream = None

    # -- public helpers -----------------------------------------------------

    @property
    def config(self) -> SootheConfig:
        """The active configuration."""
        return self._config

    @property
    def current_thread_id(self) -> str | None:
        """Thread ID for the active session, or `None`."""
        return self._current_thread_id

    @property
    def current_plan(self) -> Plan | None:
        """The current plan, or `None`."""
        return self._current_plan

    def set_current_thread_id(self, thread_id: str | None) -> None:
        """Set the active thread ID used by future runs.

        Args:
            thread_id: Thread ID to reuse, or `None` to clear.
        """
        self._current_thread_id = thread_id

    def _clear_query_scoped_runner_state(self) -> None:
        """Clear per-query mirrors on this singleton runner.

        Per-call state is held in local variables of `astream`; this resets
        CLI/debug pointers so cancelled or completed runs do not leak into
        the next `astream` invocation.
        """
        self._current_plan = None

    def thread_context_manager(self) -> Any:
        """Return `ThreadContextManager` for durability/thread operations.

        Callers outside core (e.g. daemon) should use this instead of reading
        `runner._durability` directly.
        """
        from ._thread_manager import ThreadContextManager

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

    async def get_sloop_shared_pool(self) -> Any:
        """Get or initialize the shared PostgreSQL pool for StrangeLoop state.

        Singleton pool for high-concurrency (200+ threads) support.
        Pool is shared across all StrangeLoopStateManager instances.

        Returns:
            SharedPostgreSQLPool instance if PostgreSQL configured, None for SQLite.
        """
        if self._sloop_shared_pool is not None:
            return self._sloop_shared_pool

        if self._config.persistence.default_backend != "postgresql":
            return None

        from soothe.sloop.checkpoints.shared_pool import SharedPostgreSQLPool

        self._sloop_shared_pool = await SharedPostgreSQLPool.get_shared_instance(self._config)
        from soothe.persistence.loop_writer import LoopPersistenceWriter

        await LoopPersistenceWriter.get_shared_instance(
            self._config,
            shared_pool=self._sloop_shared_pool,
        )
        return self._sloop_shared_pool

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

    async def delete_checkpoint_thread(self, thread_id: str) -> None:
        """Delete LangGraph checkpoint rows for `thread_id`.

        Delegates to the LangGraph saver's `adelete_thread` to remove
        rows from the `checkpoints` / `writes` / `checkpoint_blobs`
        tables. When the checkpointer is not materialized (lazy init), opens
        a temporary connection to the checkpointer pool to run the deletes
        directly — the daemon's utility runner may never materialize the
        checkpointer since queries run in subprocesses.
        """
        checkpointer = self._checkpointer
        if checkpointer is not None:
            try:
                await checkpointer.adelete_thread(thread_id)
                logger.debug("Deleted LangGraph checkpoint thread %s", thread_id)
                return
            except Exception:
                logger.debug(
                    "Failed to delete LangGraph checkpoint thread %s", thread_id, exc_info=True
                )
                return
        # Checkpointer not materialized — open a temporary connection to the
        # shared pool and delete directly.
        await self._delete_checkpoint_thread_via_pool(thread_id)

    async def _delete_checkpoint_thread_via_pool(self, thread_id: str) -> None:
        """Delete checkpoint rows via a temporary connection to the pool."""
        pool = self._checkpointer_pool
        if pool is None:
            return
        try:
            if isinstance(pool, str):
                # SQLite path.
                import aiosqlite

                async with aiosqlite.connect(pool) as conn:
                    await conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
                    await conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
                    await conn.commit()
            else:
                # Postgres pool.
                async with pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,)
                        )
                        await cur.execute(
                            "DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread_id,)
                        )
                        await cur.execute(
                            "DELETE FROM checkpoint_blobs WHERE thread_id = %s", (thread_id,)
                        )
            logger.debug("Deleted LangGraph checkpoint thread %s (via pool)", thread_id)
        except Exception:
            logger.debug("Failed to delete checkpoint thread %s via pool", thread_id, exc_info=True)

    async def list_checkpoint_thread_ids(self, prefix: str) -> list[str]:
        """Return distinct LangGraph checkpoint thread ids matching `prefix`.

        Queries the `checkpoints` table directly (bypasses the durability
        index, which does not register fork threads). Used by GC to find
        execute-step / synth / intake threads that share the
        `{loop_id}__` prefix. Opens a temporary connection to the
        checkpointer pool when the checkpointer is not materialized.
        """
        # Try the materialized checkpointer first.
        checkpointer = self._checkpointer
        conn = getattr(checkpointer, "conn", None) if checkpointer else None
        if conn is not None:
            result = await self._query_checkpoint_thread_ids(conn, prefix)
            if result is not None:
                return result
        # Fall back to a temporary connection via the pool.
        pool = self._checkpointer_pool
        if pool is None:
            return []
        try:
            if isinstance(pool, str):
                import aiosqlite

                async with aiosqlite.connect(pool) as conn:
                    return await self._query_checkpoint_thread_ids(conn, prefix) or []
            else:
                async with pool.connection() as conn:
                    return await self._query_checkpoint_thread_ids(conn, prefix) or []
        except Exception:
            logger.debug(
                "Failed to list checkpoint thread ids for prefix %s", prefix, exc_info=True
            )
            return []

    async def _query_checkpoint_thread_ids(self, conn: Any, prefix: str) -> list[str] | None:
        """Query distinct thread_ids matching prefix. Returns None on failure."""
        pattern = f"{prefix}%"
        try:
            # Postgres pools expose ``connection()`` but not ``cursor()``;
            # SQLite connections expose ``cursor()``.
            if hasattr(conn, "connection") and not hasattr(conn, "cursor"):
                # Already a Postgres pool — get a connection from it.
                async with conn.connection() as pg_conn:
                    async with pg_conn.cursor() as cur:
                        await cur.execute(
                            "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE %s",
                            (pattern,),
                        )
                        rows = await cur.fetchall()
                return [r[0] for r in rows if r and r[0]]
            # SQLite connection.
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE ?",
                    (pattern,),
                )
                rows = await cur.fetchall()
            return [r[0] for r in rows if r and r[0]]
        except Exception:
            logger.debug(
                "Failed to query checkpoint thread ids for prefix %s", prefix, exc_info=True
            )
            return None

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
        """Refresh `updated_at` on thread metadata (activity ping).

        When durability record is missing (e.g., after daemon restart with existing loop),
        attempts recovery via ThreadContextManager._recover_missing_thread_metadata to
        restore thread metadata from run artifacts.
        """
        if not thread_id:
            return
        try:
            # Empty merge still reloads and persists with a fresh ``ThreadInfo.updated_at``
            # (``get_thread`` can be None for non-durability / not-yet-created records).
            await self._durability.update_thread_metadata(thread_id, {})
            logger.debug("Thread %s updated_at refreshed", thread_id)
        except KeyError:
            # Durability record missing - attempt recovery for loop threads
            # (e.g., daemon restarted while TUI held existing loop_id)
            logger.debug(
                "touch_thread_activity_timestamp: no durability record for %s, attempting recovery",
                thread_id,
            )
            try:
                tcm = self.thread_context_manager()
                await tcm._recover_missing_thread_metadata(thread_id)
                logger.info("Recovered durability metadata for thread %s", thread_id)
            except KeyError:
                # Recovery failed - no run artifacts exist
                logger.debug(
                    "touch_thread_activity_timestamp: recovery failed for %s (no run artifacts)",
                    thread_id,
                )
            except Exception:
                logger.debug(
                    "touch_thread_activity_timestamp: recovery attempt failed for %s",
                    thread_id,
                    exc_info=True,
                )
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
        """List threads with optional `ThreadFilter` (daemon / tooling)."""
        return await self._durability.list_threads(thread_filter)

    async def cleanup(self) -> None:
        """Clean up resources during shutdown.

        Stops background indexer tasks and closes connection pools.
        Closes shared StrangeLoop PostgreSQL pool at daemon shutdown.

        For SQLite checkpointers, closes the underlying `aiosqlite` connection.
        That library runs a non-daemon worker thread; leaving it open prevents the
        process from exiting after standalone examples / one-shot runners finish.
        """
        if self._checkpointer_pool is not None:
            try:
                # Check if pool is a string (SQLite path) or an object (PostgreSQL pool)
                is_sqlite = isinstance(self._checkpointer_pool, str)
            except Exception:
                is_sqlite = False

            try:
                if is_sqlite:
                    await self._close_sqlite_checkpointer()
                else:
                    from soothe.runner.resolver.shared_checkpointer_pool import (
                        SharedCheckpointerPool,
                    )

                    if not SharedCheckpointerPool.is_shared_pool(self._checkpointer_pool):
                        await self._checkpointer_pool.close()
                        logger.info("Closed PostgreSQL checkpointer connection pool")
                    # Shared singleton is closed at daemon shutdown (LoopRunnerFactory).
            except Exception:
                logger.debug("Failed to close checkpointer pool", exc_info=True)

        # Clear reference to shared StrangeLoop PostgreSQL pool
        # NOTE: Do NOT close the global singleton here - it's shared across all threads
        # in thread_pool mode. Pool is closed at daemon shutdown via LoopRunnerFactory.
        self._sloop_shared_pool = None

        # Close durability / memory stores attached to this runner (Runtime-backed when SQLite).
        await self._close_attached_store(self._durability)

        await self._close_attached_store(self._memory)

    async def get_thread_state_values(self, thread_id: str) -> dict[str, Any]:
        """Return checkpoint state values for a thread.

        Args:
            thread_id: Thread identifier to inspect.

        Returns:
            State values keyed by channel name. Empty when no checkpoint exists.
        """
        # Agent may not expose a LangGraph graph (e.g. lazy/unmaterialized)
        if not hasattr(self._core_agent, "graph"):
            return {}

        await self._ensure_checkpointer_initialized()
        config = {"configurable": {"thread_id": thread_id}}
        state = await self._materialized_core_agent().graph.aget_state(config)
        if state and state.values:
            return dict(state.values)
        return {}

    async def update_thread_state_values(
        self,
        thread_id: str,
        values: dict[str, Any],
        *,
        as_node: str | None = "model",
    ) -> None:
        """Persist partial checkpoint state for a thread.

        Args:
            thread_id: Thread identifier to update.
            values: Partial state values to write.
            as_node: Node to attribute the write to. Defaults to `"model"`,
                the soothe_deepagents/langchain agent node that owns the `messages`
                channel. LangGraph requires this when multiple nodes have
                written at the current checkpoint version.
        """
        # Agent may not expose a LangGraph graph (e.g. lazy/unmaterialized)
        if not hasattr(self._core_agent, "graph"):
            return

        await self._ensure_checkpointer_initialized()
        config = {"configurable": {"thread_id": thread_id}}
        await self._materialized_core_agent().graph.aupdate_state(config, values, as_node=as_node)

    async def _close_sqlite_checkpointer(self) -> None:
        """Close the runner-owned AsyncSqliteSaver `aiosqlite` connection."""
        checkpointer = getattr(self, "_checkpointer", None)
        if checkpointer is None:
            return
        conn = getattr(checkpointer, "conn", None)
        if conn is not None:
            await self._safe_close(conn)
            logger.info("Closed SQLite checkpointer aiosqlite connection")
        # Drop graph pointer so a later materialize does not reuse a closed conn.
        try:
            from soothe.coreagent.lazy import LazyCoreAgent

            agent = self._core_agent
            if isinstance(agent, LazyCoreAgent) and not agent.is_materialized:
                agent = None
            graph = getattr(agent, "graph", None) if agent is not None else None
            if graph is not None and getattr(graph, "checkpointer", None) is checkpointer:
                graph.checkpointer = None
        except Exception:
            logger.debug("Failed to clear graph checkpointer after close", exc_info=True)
        self._checkpointer = None
        self._checkpointer_initialized = False

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

    # -- main stream --------------------------------------------------------

    def set_clarification_mode(self, mode: str) -> bool:
        """Hot-swap the clarification mode on the running goal.

        Forwards to the live `StrangeLoop` instance, which rebuilds the
        `ClarificationPolicy` and swaps it on the active `LoopRuntimeContext`.
        The next `await_clarification` node entry uses the new mode.

        Args:
            mode: `"auto"` or `"manual"`.

        Returns:
            `True` when the swap landed on a live goal; `False` when no
            goal is running (the caller may retry on the next turn).
        """
        agent = self._live_loop_agent
        if agent is None:
            return False
        return agent.set_clarification_mode(mode)

    async def astream(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
        workspace: str | None = None,
        preferred_subagent: str | None = None,
        intake_scope: str | None = None,
        client_loop_id: str | None = None,
        autopilot_job: Any = None,  # GoalDispatchEnvelope | None — see RFC-222 revised
        clarification_mode: str | None = None,  # RFC-622 per-request override
        interaction_mode: str | None = None,  # per-request "agent"|"ask" graph selection
        clarification_answer: bool = False,  # RFC-622: resume hint
        clarification_answers: list[str] | None = None,  # RFC-622: per-question answers
        resume_interrupted: bool = False,  # daemon crash recovery
        approved_plan_path: str | None = None,  # Bug #3: plan-mode approve exec goal
    ) -> AsyncGenerator[StreamChunk]:
        """Stream agent execution with protocol orchestration.

        Yields `(namespace, mode, data)` tuples in the canonical
        format.  Protocol events are emitted as `custom` events with
        `soothe.*` type prefix.

        **Two execution modes** (selected in priority order):
        - `autopilot_job` set: daemon-dispatched goal, runs
          `_run_autopilot_job` which hydrates from the bundle and emits a
          `GoalCompletionChunk` at the end. StrangeLoop never sees the DAG.
          `user_input` is ignored.
        - Default: Agentic loop with Reason → Act iteration.

        Args:
            user_input: The user's query text.
            thread_id: Thread ID for persistence. Generated if not provided.
            workspace: Thread-specific workspace path. When omitted, resolved via
                `resolve_workspace_for_stream` (daemon default, then cwd). The
                resolved path is always a non-empty absolute directory string for this call.
            preferred_subagent: Optional subagent hint merged into StrangeLoop.
            intake_scope: Optional client-forced intake scope
                (`minimal`|`simple`|`complex`); skips the intake LLM when set.
            client_loop_id: Daemon client loop scope for logging and stream correlation.
            autopilot_job: When set, signals an autopilot-dispatched job.
                Worker hydrates StrangeLoop from `autopilot_job.merged_context` and runs
                `autopilot_job.goal_description`; `user_input` is ignored. Emits a
                `GoalCompletionChunk` exactly once before the terminal chunk.
                `None` (default) keeps today's behavior.
            clarification_mode: per-request mode (`"auto"` / `"manual"`).
                `None` falls back to `config.agent.clarification.default_mode`.
                Ignored when `autopilot_job` is set (autopilot forces `"auto"`).
            interaction_mode: per-request CoreAgent interaction mode
                (`"agent"` / `"ask"`). `"ask"` selects the read-only graph
                (tools restricted to read-only FS ops, writes denied). `None`
                uses the default `"agent"` graph.
            clarification_answer: When True, hints that `user_input` is the
                answer to a pending clarification. The runner verifies via the
                loop's persisted state and resumes the graph via
                `Command(resume=...)`; falls back to a normal turn when no
                clarification is actually pending.
            clarification_answers: Per-question answer list for multi-question
                clarifications. When provided alongside `clarification_answer`,
                resumes the graph with one answer per question instead of
                broadcasting a single string. `None` falls back to treating
                `user_input` as a single answer string (broadcast to all
                questions if there are several).
        """
        # Update thread_id for logging if one is provided
        from soothe.logging import set_thread_id
        from soothe.workspace import resolve_daemon_workspace

        cl_scope = (client_loop_id or "").strip()
        # Prefer client loop scope for log tags so worker runner.log matches daemon loop_id.
        log_scope = cl_scope or str(thread_id or self._current_thread_id or "").strip()
        if log_scope:
            set_thread_id(log_scope)
        prev_client_loop = self._client_loop_id_for_stream
        self._client_loop_id_for_stream = cl_scope or None
        try:
            resolved = resolve_workspace_for_stream(
                explicit=workspace,
                installation_default=str(resolve_daemon_workspace()),
            )
            effective_workspace = resolved.path
            tid_for_log = log_scope
            logger.debug(
                "stream_workspace_resolved thread_id=%s path=%s source=%s",
                tid_for_log,
                effective_workspace,
                resolved.source,
            )

            loop_max = self._config.agent.loop.max_iterations

            # RFC-222 revised: autopilot-dispatched job takes priority.
            # StrangeLoop runs the single goal hydrated from the bundle; ignores user_input.
            if autopilot_job is not None:
                async for chunk in self._run_autopilot_job(
                    autopilot_job,
                    thread_id=thread_id,
                    workspace=effective_workspace,
                    max_iterations=loop_max,
                    intake_scope=intake_scope,
                ):
                    yield chunk
                return

            # Default: StrangeLoop execution (RFC-0008)
            async for chunk in self._run_strange_loop(
                user_input,
                thread_id=thread_id,
                workspace=effective_workspace,
                max_iterations=loop_max,
                preferred_subagent=preferred_subagent,
                intake_scope=intake_scope,
                clarification_mode=clarification_mode,
                interaction_mode=interaction_mode,
                clarification_answer=clarification_answer,
                clarification_answers=clarification_answers,
                resume_interrupted=resume_interrupted,
                approved_plan_path=approved_plan_path,
            ):
                yield chunk
        finally:
            self._client_loop_id_for_stream = prev_client_loop
            self._clear_query_scoped_runner_state()

    async def _run_autopilot_job(
        self,
        _job: Any,
        *,
        thread_id: str | None,
        workspace: str,
        max_iterations: int,
        intake_scope: str | None = None,
    ) -> AsyncGenerator[StreamChunk]:
        """Run an autopilot-dispatched goal (overridden by `AutopilotSootheRunner`).

        The base `SootheRunner` is autopilot-agnostic: it must never receive a
        non-`None` `autopilot_job`. The daemon constructs
        `soothe_autopilot.AutopilotSootheRunner` in autopilot worker loops; that
        subclass overrides this hook with the goal-dispatch implementation.

        Raises:
            RuntimeError: If a bare `SootheRunner` receives an `autopilot_job`.
        """
        raise RuntimeError(
            "autopilot_job reached a non-autopilot SootheRunner; construct "
            "soothe_autopilot.AutopilotSootheRunner in autopilot workers"
        )
