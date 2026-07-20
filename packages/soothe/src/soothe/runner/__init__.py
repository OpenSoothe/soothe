"""SootheRunner -- protocol-orchestrated agent runner (RFC-0003, RFC-0007, RFC-0008).

Wraps `create_soothe_agent()` with protocol pre/post-processing and
yields the canonical ``(namespace, mode, data)`` stream
extended with ``soothe.*`` custom events for protocol observability.

RFC-0008 adds agentic loop: default execution mode with Reason → Act
iterative refinement loop (RFC-201) via ``StrangeLoop`` and the compiled
loop graph (RFC-220). DAG-style multi-step execution is implemented
inside the StrangeLoop execute phase (``StepScheduler`` / ``Executor``),
not as a separate runner mixin.

RFC-222 Phase D: the legacy in-process autonomous multi-goal loop has
been removed. Autopilot is daemon-owned; goals dispatched by the daemon
arrive through ``LoopRunRequest.autopilot_job`` and route to the
single-goal worker path.

Implementation is decomposed into mixins:

- `PhasesMixin`     -- chitchat fast path and checkpointer initialization
- `StrangeLoopMixin` -- StrangeLoop execution (RFC-0008)
- `AutopilotWorkerMixin` -- single-goal worker entry (RFC-222 revised)
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from soothe_sdk.protocols.planner import Plan, PlannerProtocol
from soothe_sdk.protocols.policy import PolicyProtocol

from soothe.config import SootheConfig
from soothe.foundation.workspace import resolve_workspace_for_stream

from ._runner_autopilot_worker import AutopilotWorkerMixin
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

    from soothe.foundation.coreagent.coding.lazy import LazyCoreAgent
    from soothe.foundation.identity.runtime import IdentityRuntime

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SootheRunner
# ---------------------------------------------------------------------------


class SootheRunner(
    AutopilotWorkerMixin,
    StrangeLoopMixin,
    PhasesMixin,
):
    """Protocol-orchestrated agent runner.

    Wraps ``create_soothe_agent()`` with pre/post protocol steps and
    provides ``astream()`` that yields the canonical stream
    format extended with ``soothe.*`` protocol custom events.

    Args:
        config: Soothe configuration. If ``None``, uses defaults.
    """

    def __init__(
        self,
        config: SootheConfig | None = None,
        *,
        identity_runtime: IdentityRuntime | None = None,
    ) -> None:
        """Initialize the runner with optional config.

        Args:
            config: Soothe configuration. If ``None``, uses defaults.
            identity_runtime: Optional identity bundle (RFC-307). When enabled,
                IdentityMiddleware is prepended to the agent middleware stack.
        """
        import time

        from soothe_sdk.protocols.concurrency import ConcurrencyPolicy

        from soothe.foundation.coreagent import create_soothe_agent
        from soothe.foundation.coreagent.coding.lazy import LazyCoreAgent
        from soothe.foundation.sloop.intention import IntentClassifier
        from soothe.runner.resolver import (
            resolve_checkpointer,
            resolve_durability,
            resolve_planner,
            resolve_policy,
        )

        from ._concurrency import ConcurrencyController

        init_start = time.perf_counter()

        self._config = config or SootheConfig()
        self._identity_runtime = identity_runtime
        self._checkpointer_pool = None  # Will be set if using PostgreSQL

        # Initialize intent classifier (IG-226: core.intention module).
        # Unified classification is always enabled; classifier is omitted only if fast model is unavailable.
        fast_model = None
        try:
            fast_model = self._config.create_chat_model("fast")
        except Exception:
            logger.exception(
                "Failed to create fast model for classification. Classification will be disabled."
            )
            fast_model = None

        self._fast_model: Any | None = fast_model
        if fast_model:
            self._intent_classifier = IntentClassifier(
                model=fast_model,
                assistant_name=self._config.agent.name,
                soothe_config=self._config,
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

        default_model_instance = None
        try:
            default_model_instance = self._config.create_chat_model("default")
        except Exception:
            logger.debug("Default chat model unavailable for planner resolution", exc_info=True)

        self._planner: PlannerProtocol | None = resolve_planner(
            self._config, default_model_instance
        )
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

        durability_start = time.perf_counter()
        self._durability = resolve_durability(self._config)
        durability_ms = (time.perf_counter() - durability_start) * 1000
        logger.debug("Durability resolved in %.1fms", durability_ms)

        self._current_thread_id: str | None = None
        self._current_plan: Plan | None = None
        _concurrency_cfg = self._config.agent.loop.concurrency
        self._concurrency = ConcurrencyController(
            ConcurrencyPolicy(
                max_parallel_goals=_concurrency_cfg.max_parallel_goals,
                max_parallel_steps=_concurrency_cfg.max_parallel_steps,
                max_parallel_subagents=_concurrency_cfg.max_parallel_subagents,
                global_max_llm_calls=_concurrency_cfg.global_max_llm_calls,
                step_parallelism=_concurrency_cfg.step_parallelism,
            )
        )
        self._context_restore_lock = asyncio.Lock()
        # Client-visible loop id for the active ``astream`` (daemon loop scope / logging).
        self._client_loop_id_for_stream: str | None = None

        # IG-406: Shared PostgreSQL pool for StrangeLoop state persistence
        # Initialized lazily in async context for high-concurrency support
        self._sloop_shared_pool: Any = None  # SharedPostgreSQLPool | None

        total_ms = (time.perf_counter() - init_start) * 1000
        logger.info("SootheRunner initialized in %.1fms", total_ms)

    @property
    def _agent(self) -> CoreAgentProtocol | LazyCoreAgent:
        """Layer-1 agent handle (lazy or materialized)."""
        return self._core_agent

    async def _materialize_core_agent(self) -> CoreAgentProtocol:
        """Ensure CoreAgent graph is compiled and checkpointer is attached."""
        from soothe.foundation.coreagent.coding.lazy import LazyCoreAgent

        if isinstance(self._core_agent, LazyCoreAgent):
            return await self._core_agent.amaterialize()
        await self._ensure_checkpointer_initialized()
        return self._core_agent

    def _materialized_core_agent(self) -> CoreAgentProtocol:
        """Return a compiled CoreAgent, materializing lazily when needed."""
        from soothe.foundation.coreagent.coding.lazy import LazyCoreAgent

        if isinstance(self._core_agent, LazyCoreAgent):
            return self._core_agent.materialize()
        return self._core_agent

    def prepare_for_request(self) -> None:
        """Reset per-request runner mirrors without recompiling CoreAgent (IG-506)."""
        self._clear_query_scoped_runner_state()
        self._client_loop_id_for_stream = None

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

        Authoritative plan data lives on ``RunnerState`` per call;
        this resets CLI/debug pointers so cancelled or completed runs do not
        leak into the next ``astream`` invocation.
        """
        self._current_plan = None

    def thread_context_manager(self) -> Any:
        """Return ``ThreadContextManager`` for durability/thread operations (IG-110).

        Callers outside core (e.g. daemon) should use this instead of reading
        ``runner._durability`` directly.
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

        IG-406: Singleton pool for high-concurrency (200+ threads) support.
        Pool is shared across all StrangeLoopStateManager instances.

        Returns:
            SharedPostgreSQLPool instance if PostgreSQL configured, None for SQLite.
        """
        if self._sloop_shared_pool is not None:
            return self._sloop_shared_pool

        if self._config.persistence.default_backend != "postgresql":
            return None

        from soothe.foundation.sloop.state.persistence.shared_pool import SharedPostgreSQLPool

        self._sloop_shared_pool = await SharedPostgreSQLPool.get_shared_instance(self._config)
        from soothe.foundation.persistence.loop_writer import LoopPersistenceWriter

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
        """Refresh ``updated_at`` on thread metadata (activity ping).

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
        """List threads with optional ``ThreadFilter`` (daemon / tooling)."""
        return await self._durability.list_threads(thread_filter)

    async def cleanup(self) -> None:
        """Clean up resources during shutdown.

        Stops background indexer tasks and closes connection pools.
        IG-406: Closes shared StrangeLoop PostgreSQL pool at daemon shutdown.
        """
        if self._checkpointer_pool is not None:
            try:
                # Check if pool is a string (SQLite path) or an object (PostgreSQL pool)
                is_sqlite = isinstance(self._checkpointer_pool, str)
            except Exception:
                is_sqlite = False

            try:
                if not is_sqlite:
                    from soothe.runner.resolver.shared_checkpointer_pool import (
                        SharedCheckpointerPool,
                    )

                    if not SharedCheckpointerPool.is_shared_pool(self._checkpointer_pool):
                        await self._checkpointer_pool.close()
                        logger.info("Closed PostgreSQL checkpointer connection pool")
                    # Shared singleton is closed at daemon shutdown (LoopRunnerFactory).
                # SQLite checkpointer manages its own connection via AsyncSqliteSaver
            except Exception:
                logger.debug("Failed to close checkpointer pool", exc_info=True)

        # IG-406: Clear reference to shared StrangeLoop PostgreSQL pool
        # NOTE: Do NOT close the global singleton here - it's shared across all threads
        # in thread_pool mode. Pool is closed at daemon shutdown via LoopRunnerFactory.
        self._sloop_shared_pool = None

        # IG-404: Close durability backend connection pool (SQLitePersistStore)
        # Each runner creates its own SQLitePersistStore with writer + reader pool.
        # Must close to prevent file descriptor exhaustion.
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
            as_node: Node to attribute the write to. Defaults to ``"model"``,
                the soothe_deepagents/langchain agent node that owns the ``messages``
                channel. LangGraph requires this when multiple nodes have
                written at the current checkpoint version.
        """
        # Agent may not expose a LangGraph graph (e.g. lazy/unmaterialized)
        if not hasattr(self._core_agent, "graph"):
            return

        await self._ensure_checkpointer_initialized()
        config = {"configurable": {"thread_id": thread_id}}
        await self._materialized_core_agent().graph.aupdate_state(config, values, as_node=as_node)

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

    async def astream(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
        workspace: str | None = None,
        max_iterations: int | None = None,
        preferred_subagent: str | None = None,
        client_loop_id: str | None = None,
        autopilot_job: Any = None,  # GoalDispatchEnvelope | None — see RFC-222 revised
        clarification_mode: str | None = None,  # RFC-622 per-request override
        clarification_answer: bool = False,  # RFC-622: resume hint
        clarification_answers: list[str] | None = None,  # RFC-622: per-question answers
    ) -> AsyncGenerator[StreamChunk]:
        """Stream agent execution with protocol orchestration.

        Yields ``(namespace, mode, data)`` tuples in the canonical
        format.  Protocol events are emitted as ``custom`` events with
        ``soothe.*`` type prefix.

        **Two execution modes** (selected in priority order):
        - ``autopilot_job`` set (RFC-222 revised): daemon-dispatched goal, runs
          ``_run_single_autopilot_goal`` which hydrates from the bundle and
          emits a ``GoalCompletionChunk`` at the end. StrangeLoop never sees the
          DAG. ``user_input`` is ignored.
        - Default (RFC-201): Agentic loop with Reason → Act iteration.

        Args:
            user_input: The user's query text.
            thread_id: Thread ID for persistence. Generated if not provided.
            workspace: Thread-specific workspace path (RFC-103). When omitted, resolved via
                ``resolve_workspace_for_stream`` (daemon default, then cwd). The
                resolved path is always a non-empty absolute directory string for this call.
            max_iterations: Override max iterations from config.
            preferred_subagent: Optional subagent hint merged into StrangeLoop (IG-349).
            client_loop_id: Daemon client loop scope for logging and stream correlation.
            autopilot_job: When set, signals an autopilot-dispatched job (RFC-222 revised).
                Worker hydrates StrangeLoop from ``autopilot_job.merged_context`` and runs
                ``autopilot_job.goal_description``; ``user_input`` is ignored. Emits a
                ``GoalCompletionChunk`` exactly once before the terminal chunk.
                ``None`` (default) keeps today's behavior.
            clarification_mode: RFC-622 per-request mode (``"auto"`` / ``"manual"``).
                ``None`` falls back to ``config.agent.clarification.default_mode``.
                Ignored when ``autopilot_job`` is set (autopilot forces ``"auto"``).
            clarification_answer: When True, hints that ``user_input`` is the
                answer to a pending clarification. The runner verifies via the
                loop's persisted state and resumes the graph via
                ``Command(resume=...)``; falls back to a normal turn when no
                clarification is actually pending.
            clarification_answers: Per-question answer list for multi-question
                clarifications. When provided alongside ``clarification_answer``,
                resumes the graph with one answer per question instead of
                broadcasting a single string. ``None`` falls back to treating
                ``user_input`` as a single answer string (broadcast to all
                questions if there are several).
        """
        # Update thread_id for logging if one is provided
        from soothe.foundation.workspace import resolve_daemon_workspace
        from soothe.logging import set_thread_id

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

            # RFC-222 revised: autopilot-dispatched job takes priority
            # over autonomous= flag. StrangeLoop runs the single goal hydrated
            # from the bundle; ignores user_input.
            if autopilot_job is not None:
                async for chunk in self._run_single_autopilot_goal(
                    autopilot_job,
                    thread_id=thread_id,
                    workspace=effective_workspace,
                    max_iterations=max_iterations or self._config.agent.loop.max_iterations,
                ):
                    yield chunk
                return

            # Default: StrangeLoop execution (RFC-0008)
            async for chunk in self._run_strange_loop(
                user_input,
                thread_id=thread_id,
                workspace=effective_workspace,
                max_iterations=max_iterations or self._config.agent.loop.max_iterations,
                preferred_subagent=preferred_subagent,
                clarification_mode=clarification_mode,
                clarification_answer=clarification_answer,
                clarification_answers=clarification_answers,
            ):
                yield chunk
        finally:
            self._client_loop_id_for_stream = prev_client_loop
            self._clear_query_scoped_runner_state()
