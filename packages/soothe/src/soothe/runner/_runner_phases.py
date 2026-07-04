"""Phase orchestration mixin for SootheRunner (pre-stream helpers).

Extracted from ``runner.py`` to keep the main module focused on orchestration.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from soothe_sdk.core.exceptions import ConfigurationError

from soothe.foundation.events import (
    LoopCreatedEvent,
    LoopStartedEvent,
    PlanCreatedEvent,
)
from soothe.foundation.sloop.utils.messages import loop_assistant_messages_chunk
from soothe.protocols.planner import PlanContext
from soothe.protocols.policy import ActionRequest, PolicyContext

from ._runner_shared import StreamChunk, _custom, _validate_goal

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langchain_core.messages import BaseMessage


logger = logging.getLogger(__name__)

# IG-157: wake periodically for cooperative cancellation without cancelling the stream read (IG-193)
_STREAM_POLL_INTERVAL_S = 0.5


async def _await_next_astream_chunk(chunk_iter: AsyncIterator[Any]) -> Any:
    """Wait for the next ``astream`` chunk with periodic cancellation checks.

    ``asyncio.wait_for(anext(), timeout)`` cancels the awaited ``__anext__()`` when
    the timeout fires. That breaks iterators that legitimately take longer than
    the poll interval between chunks (typical for LLM calls). Here we use
    ``asyncio.wait(..., timeout=...)``, which does not cancel the pending read when
    the interval elapses; we only cancel the read when the runner task is
    cancelling.

    Args:
        chunk_iter: Async iterator from ``CompiledStateGraph.astream``.

    Returns:
        The next chunk tuple from the graph.

    Raises:
        StopAsyncIteration: When the graph stream is exhausted.
        asyncio.CancelledError: When the current task is cancelled cooperatively.
    """
    anext_task = asyncio.create_task(chunk_iter.__anext__())
    try:
        while not anext_task.done():
            await asyncio.wait({anext_task}, timeout=_STREAM_POLL_INTERVAL_S)
            if anext_task.done():
                break
            current_task = asyncio.current_task()
            if current_task and current_task.cancelling():
                logger.info("Runner stream detected cancellation request, stopping")
                anext_task.cancel()
                try:
                    await anext_task
                except asyncio.CancelledError:
                    pass
                raise asyncio.CancelledError
        return anext_task.result()
    finally:
        if not anext_task.done():
            anext_task.cancel()
            try:
                await anext_task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass


class PhasesMixin:
    """Protocol pre/post-processing and LangGraph streaming.

    Mixed into ``SootheRunner`` -- all ``self.*`` attributes are defined
    on the concrete class.
    """

    # -- quiz fast path (greetings + trivia, IG-250) -----------------------

    async def _run_quiz(
        self,
        user_input: str,
        thread_id: str,
        classification: Any | None = None,
        *,
        context_engine: Any | None = None,
    ) -> AsyncGenerator[StreamChunk]:
        """Fast path for quiz-style queries (greetings, thanks, brief trivia).

        Uses piggybacked ``quiz_response`` from intent classification when
        available (avoiding a second LLM call). Falls back to a separate
        LLM invocation when the classification did not provide an answer.

        Args:
            user_input: User message.
            thread_id: Thread ID for state tracking.
            classification: IntentClassification from classifier (may contain piggybacked quiz_response).
            context_engine: Optional loop ContextEngine for ledger persistence.

        Yields:
            StreamChunk events for quiz response.
        """
        logger.info("Quiz: %s", user_input[:50])

        # Use piggybacked quiz_response from intent classification (avoids second LLM call)
        piggybacked_answer = None
        if classification is not None:
            piggybacked_answer = getattr(classification, "quiz_response", None)
            if isinstance(piggybacked_answer, str) and piggybacked_answer.strip():
                logger.debug("Quiz using piggybacked answer from classification")
                yield loop_assistant_messages_chunk(
                    content=piggybacked_answer.strip(),
                    phase="quiz",
                    thread_id=thread_id,
                )
                self._schedule_quiz_persistence(
                    user_input,
                    piggybacked_answer.strip(),
                    thread_id,
                    context_engine=context_engine,
                )
                return

        # Fallback: separate LLM call for quiz answer
        quiz_model = getattr(self, "_fast_model", None)
        model_label = "fast"
        if not quiz_model:
            quiz_model = getattr(self, "_default_chat_model", None)
            model_label = "default"
        if not quiz_model:
            quiz_model = getattr(self, "_model", None)
            model_label = "think"
        if not quiz_model:
            fallback_response = f"I'll answer that question: {user_input}"
            yield loop_assistant_messages_chunk(
                content=fallback_response,
                phase="quiz",
                thread_id=thread_id,
            )
            logger.debug("Quiz completed (no model fallback): %s", user_input[:50])
            self._schedule_quiz_persistence(
                user_input,
                fallback_response,
                thread_id,
                context_engine=context_engine,
            )
            return

        from soothe.foundation.sloop.intention.quiz_messages import build_quiz_system_message

        assistant_name = getattr(getattr(self._config, "agent", None), "name", None) or "Soothe"
        quiz_user_prompt = f"""Answer this question accurately and concisely using only your training knowledge.

Question: {user_input}

Provide a direct, factual answer for static facts, greetings, or simple math.
Do not use tools or search. If the question needs live/real-time data (weather, news, stocks, etc.), say you cannot provide current data and suggest checking an authoritative source."""

        quiz_messages = [
            SystemMessage(content=build_quiz_system_message(assistant_name)),
            HumanMessage(content=quiz_user_prompt),
        ]

        try:
            from soothe.utils.llm.invoke_policy import (
                await_with_llm_call_policy,
                llm_rate_limit_config_from,
            )
            from soothe.utils.observability.langfuse import SootheLangfuse

            quiz_config = SootheLangfuse(self._config).traced_llm(
                purpose="quiz_answer",
                component="runner.quiz",
                phase="pre-stream",
                session_id=thread_id,
                run_name="soothe:quiz",
                independent_trace=True,
            )

            async def _invoke() -> Any:
                return await quiz_model.ainvoke(quiz_messages, config=quiz_config)

            response = await await_with_llm_call_policy(
                _invoke,
                config=llm_rate_limit_config_from(self._config),
                thread_id=thread_id,
            )
            answer = response.content if hasattr(response, "content") else str(response)

            yield loop_assistant_messages_chunk(
                content=answer,
                phase="quiz",
                thread_id=thread_id,
            )
            logger.debug("Quiz completed (%s model): %s", model_label, user_input[:50])
            self._schedule_quiz_persistence(
                user_input, answer, thread_id, context_engine=context_engine
            )
        except Exception:
            logger.exception("Quiz LLM call failed")
            fallback_response = "I couldn't answer that question. Please try again."
            yield loop_assistant_messages_chunk(
                content=fallback_response,
                phase="quiz",
                thread_id=thread_id,
            )
            self._schedule_quiz_persistence(
                user_input, fallback_response, thread_id, context_engine=context_engine
            )

    def _schedule_quiz_persistence(
        self,
        query: str,
        response: str,
        thread_id: str,
        *,
        context_engine: Any | None = None,
    ) -> None:
        """Persist quiz exchange without blocking the response stream."""

        async def _persist() -> None:
            try:
                await self._save_quiz_to_state(
                    query,
                    response,
                    thread_id,
                    context_engine=context_engine,
                )
            except Exception:
                logger.debug("Background quiz persistence failed", exc_info=True)

        asyncio.create_task(_persist())

    async def _save_quiz_to_state(
        self,
        query: str,
        response: str,
        thread_id: str,
        *,
        context_engine: Any | None = None,
    ) -> None:
        """Persist quiz (minimal-path) Human+AI pair to checkpointer and loop ledger."""
        await self._materialize_core_agent()
        await self._save_quiz_to_checkpointer(query, response, thread_id)
        await self._save_quiz_to_ledger(query, response, thread_id, context_engine=context_engine)

    async def _save_quiz_to_checkpointer(self, query: str, response: str, thread_id: str) -> None:
        """Persist quiz Human+AI pair to the LangGraph checkpointer."""
        await self._ensure_checkpointer_initialized()

        if not thread_id:
            return

        config = {"configurable": {"thread_id": thread_id}}

        try:
            await self._materialized_core_agent().graph.aupdate_state(
                config,
                {"messages": [HumanMessage(content=query), AIMessage(content=response)]},
                as_node="model",
            )
            logger.debug("Quiz exchange saved to checkpointer for thread %s", thread_id)
        except Exception:
            logger.debug("Failed to save quiz to checkpointer", exc_info=True)

    async def _save_quiz_to_ledger(
        self,
        query: str,
        response: str,
        thread_id: str,
        *,
        context_engine: Any | None = None,
    ) -> None:
        """Persist quiz Human+AI pair to the loop ContextEngine ledger."""
        from pathlib import Path

        from soothe.config import SOOTHE_HOME
        from soothe.foundation.context.engine import ContextEngine
        from soothe.foundation.context.persistence.factory import (
            resolve_context_engine_persistence,
        )
        from soothe.foundation.sloop.utils.messages import (
            LoopAIMessage,
            LoopHumanMessage,
            _record_ledger_message,
        )

        answer = (response or "").strip()
        if not answer:
            return

        if context_engine is not None:
            try:
                human = LoopHumanMessage(content=query, thread_id=thread_id, phase="quiz")
                ai = LoopAIMessage(content=answer, thread_id=thread_id, phase="quiz")
                _record_ledger_message(context_engine, human, "quiz")
                _record_ledger_message(context_engine, ai, "quiz")
                await context_engine.save()
                logger.debug(
                    "Quiz exchange saved to active loop ledger (loop=%s)",
                    getattr(self, "_client_loop_id_for_stream", None) or thread_id,
                )
                return
            except Exception:
                logger.debug("Failed to save quiz to active loop ledger", exc_info=True)

        loop_id = (getattr(self, "_client_loop_id_for_stream", None) or thread_id or "").strip()
        if not loop_id:
            return

        try:
            ce_config = self._config.agent.loop.context_engine
            persistence = resolve_context_engine_persistence(self._config, loop_id)
            soothe_home = Path(self._config.home) if hasattr(self._config, "home") else SOOTHE_HOME
            ce = ContextEngine(
                persistence=persistence,
                projection_config=ce_config.to_projection_config(),
                soothe_home=soothe_home,
            )
            await ce.load()
            human = LoopHumanMessage(content=query, thread_id=thread_id, phase="quiz")
            ai = LoopAIMessage(content=answer, thread_id=thread_id, phase="quiz")
            _record_ledger_message(ce, human, "quiz")
            _record_ledger_message(ce, ai, "quiz")
            await ce.save()
            logger.debug("Quiz exchange saved to loop ledger for loop %s", loop_id)
        except Exception:
            logger.debug("Failed to save quiz to loop ledger", exc_info=True)

    # -- LangGraph stream with interrupt auto-resume -------------------------

    async def _ensure_checkpointer_initialized(self) -> None:
        """Lazily initialize the async checkpointer (AsyncSqliteSaver / AsyncPostgresSaver).

        The checkpointer is created from ``self._checkpointer_pool`` and replaces
        the placeholder on ``self._core_agent.graph``.  Must be called before
        any ``core_agent.astream()`` that needs persistent thread state.

        Raises ConfigurationError if checkpointer initialization fails.
        """
        from soothe.foundation.core.agent._lazy import LazyCoreAgent

        if isinstance(self._core_agent, LazyCoreAgent) and not self._core_agent.is_materialized:
            return

        if self._checkpointer_initialized or self._checkpointer_pool is None:
            return

        agent = (
            self._core_agent.materialize()
            if isinstance(self._core_agent, LazyCoreAgent)
            else self._core_agent
        )

        # Check if agent supports LangGraph checkpointer (has .graph property)
        try:
            _ = agent.graph
        except NotImplementedError:
            # Agent doesn't use LangGraph (e.g., ClaudeCoreAgent)
            logger.debug("Agent does not support LangGraph checkpointer, skipping initialization")
            self._checkpointer_initialized = True
            return

        try:
            # Check if pool is a string (SQLite path) or an object (PostgreSQL pool)
            is_sqlite = isinstance(self._checkpointer_pool, str)
        except Exception:
            is_sqlite = False

        try:
            if is_sqlite:
                import aiosqlite
                from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
                from soothe_sdk.utils.serde import create_soothe_serde

                # Create async connection from path
                conn = await aiosqlite.connect(self._checkpointer_pool)
                checkpointer = AsyncSqliteSaver(conn, serde=create_soothe_serde())
                await checkpointer.setup()

                self._checkpointer = checkpointer
                agent.graph.checkpointer = checkpointer
                self._checkpointer_initialized = True
                logger.info(
                    "AsyncSqliteSaver created and tables initialized at %s", self._checkpointer_pool
                )
            else:
                # PostgreSQL: wrap initialization with retry for DB restart resilience
                await self._init_postgres_checkpointer_with_retry()
        except ModuleNotFoundError as exc:
            logger.error("Missing dependency for checkpointer: %s", exc)
            missing = str(exc.name) if exc.name else "unknown"
            raise ConfigurationError(
                f"Checkpointer initialization failed: missing module '{missing}'.\n"
                f"Install the required package and restart.\n"
                f"Persistent storage required - no fallback available."
            ) from exc
        except Exception as exc:
            logger.error("Failed to initialize async checkpointer: %s", exc)
            raise ConfigurationError(
                f"Checkpointer initialization failed: {exc}\n"
                f"Persistent storage required - no fallback available."
            )

    async def _init_postgres_checkpointer_with_retry(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 8.0,
    ) -> None:
        """Initialize PostgreSQL checkpointer with connection retry.

        Wraps pool.open() and checkpointer.setup() with exponential backoff
        retry for transient connection errors (AdminShutdown, server restart).

        Args:
            max_attempts: Maximum retry attempts (default: 3).
            base_delay: Initial retry delay in seconds (default: 1.0).
            max_delay: Maximum retry delay cap (default: 8.0).

        Raises:
            ConfigurationError if all retries exhausted.
        """
        from soothe.foundation.sloop.state.persistence.retry_utils import (
            is_recoverable_connection_error,
        )
        from soothe.runner.resolver.shared_checkpointer_pool import SharedCheckpointerPool

        delay = base_delay
        for attempt in range(1, max_attempts + 1):
            try:
                await self._checkpointer_pool.open()

                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
                from soothe_sdk.utils.serde import create_soothe_serde

                checkpointer = AsyncPostgresSaver(
                    self._checkpointer_pool, serde=create_soothe_serde()
                )
                if SharedCheckpointerPool.is_shared_pool(self._checkpointer_pool):
                    await SharedCheckpointerPool.setup_checkpointer(
                        self._checkpointer_pool,
                        checkpointer.setup,
                    )
                else:
                    await checkpointer.setup()

                self._checkpointer = checkpointer
                self._materialized_core_agent().graph.checkpointer = checkpointer
                self._checkpointer_initialized = True
                logger.info(
                    "AsyncPostgresSaver pool open and tables initialized, checkpointer replaced"
                )
                return
            except Exception as exc:
                # Check if this is a recoverable connection error
                if not is_recoverable_connection_error(exc):
                    logger.error(
                        "[checkpointer_init] Unrecoverable error: %s: %s",
                        type(exc).__name__,
                        exc,
                    )
                    raise

                # Last attempt - no more retries
                if attempt >= max_attempts:
                    logger.error(
                        "[checkpointer_init] All %d retries exhausted, last error: %s: %s",
                        max_attempts,
                        type(exc).__name__,
                        exc,
                    )
                    raise

                # Log retry and reset pool
                logger.warning(
                    "[checkpointer_init] Recoverable connection error on attempt %d/%d: %s. "
                    "Resetting pool and retrying in %.1fs...",
                    attempt,
                    max_attempts,
                    type(exc).__name__,
                    delay,
                )

                # Reset shared pool to force fresh connections
                if SharedCheckpointerPool.is_shared_pool(self._checkpointer_pool):
                    self._checkpointer_pool = await SharedCheckpointerPool.reset_shared_instance(
                        self._config
                    )
                    if self._checkpointer_pool is None:
                        raise RuntimeError(
                            "Failed to recreate shared checkpointer pool after reset"
                        )

                # Exponential backoff with cap
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)

        # Should never reach here
        raise RuntimeError("Unexpected retry loop exit for checkpointer initialization")

    async def _load_recent_messages(
        self,
        thread_id: str,
        *,
        limit: int = 6,
    ) -> list[BaseMessage]:
        """Load the most recent messages from the checkpointer for a thread.

        Used to provide conversation context to the unified classifier so it
        can distinguish follow-up actions (e.g. "translate that") from
        standalone minimal-path turns.

        Args:
            thread_id: Thread ID to load messages for.
            limit: Number of recent messages to return.

        Returns:
            List of recent BaseMessage instances, empty if unavailable.
        """
        if not thread_id:
            return []

        # Ensure checkpointer is initialized before accessing it
        await self._ensure_checkpointer_initialized()

        config = {"configurable": {"thread_id": thread_id}}

        try:
            state = await self._materialized_core_agent().graph.aget_state(config)
            if state and state.values:
                messages = state.values.get("messages", [])
                return list(messages[-limit:]) if messages else []
        except Exception:
            logger.debug("Failed to load recent messages from checkpointer", exc_info=True)
        return []

    def _format_recent_messages_for_classifier(
        self,
        messages: list[BaseMessage],
        *,
        max_chars: int = 300,
    ) -> str:
        """Format recent messages as a short conversation context string.

        Args:
            messages: Recent conversation messages.
            max_chars: Maximum length per message preview.

        Returns:
            Formatted string suitable for inclusion in the routing prompt.
        """
        lines = []
        for msg in messages:
            role = "User" if isinstance(msg, HumanMessage) else "Assistant"
            content = getattr(msg, "content", "")
            if not isinstance(content, str):
                content = str(content)
            preview = content[:max_chars].strip()
            if preview:
                lines.append(f"{role}: {preview}")
        return "\n".join(lines) if lines else ""

    def _format_thread_messages_for_plan(
        self,
        messages: list[BaseMessage],
        *,
        limit: int = 16,
        max_chars_per_message: int = 8000,
        last_assistant_max_chars: int = 100_000,
    ) -> list[str]:
        """Format recent thread messages for Layer-2 Plan prompts (IG-128, IG-133).

        Includes Human and AI turns only (skips tool/system messages). Uses XML tags
        for better multi-line content handling. Older turns use ``max_chars_per_message``;
        the **last** ``AIMessage`` in the tail uses ``last_assistant_max_chars`` so
        follow-ups (e.g. full-document translation) are not cut at 8k.

        Args:
            messages: Conversation messages from the checkpointer (newest slice).
            limit: Max messages to consider from the tail of ``messages``.
            max_chars_per_message: Truncation bound for non-final assistant bodies.
            last_assistant_max_chars: Truncation bound for the last assistant turn.

        Returns:
            XML-formatted strings like ``<USER>...</USER>`` / ``<ASSISTANT>...</ASSISTANT>``.
        """
        if not messages:
            return []
        tail = messages[-limit:] if len(messages) > limit else messages
        last_ai_idx: int | None = None
        for i in range(len(tail) - 1, -1, -1):
            if isinstance(tail[i], AIMessage):
                last_ai_idx = i
                break

        lines: list[str] = []
        for i, msg in enumerate(tail):
            if isinstance(msg, HumanMessage):
                tag = "USER"
            elif isinstance(msg, AIMessage):
                tag = "ASSISTANT"
            else:
                continue
            content = getattr(msg, "content", "")
            if not isinstance(content, str):
                content = str(content)
            body = content.strip()
            if not body:
                continue
            cap = (
                last_assistant_max_chars
                if isinstance(msg, AIMessage) and i == last_ai_idx
                else max_chars_per_message
            )
            if len(body) > cap:
                body = body[:cap].rstrip() + "\n[…truncated…]"
            # XML format handles multi-line content cleanly
            lines.append(f"<{tag}>\n{body}\n</{tag}>")
        return lines

    # -- pre-stream ---------------------------------------------------------

    def _ensure_runner_state_workspace(self, state: Any) -> None:
        """Set ``state.workspace`` to a resolved path when missing (IG-116).

        Ensures ``_pre_stream_planning`` / ``PlanContext`` always see an absolute
        directory, even if the caller omitted workspace.
        """
        from soothe.foundation.workspace import resolve_workspace_for_stream

        raw = getattr(state, "workspace", None)
        if isinstance(raw, str):
            if raw.strip():
                return
        elif raw is not None:
            return

        from soothe.foundation.workspace import resolve_daemon_workspace

        # Check config's filesystem_middleware.workspace_root first
        config_workspace = (
            self._config.filesystem_middleware.workspace_root
            if self._config and self._config.filesystem_middleware.workspace_root
            else None
        )

        resolved = resolve_workspace_for_stream(
            installation_default=config_workspace or str(resolve_daemon_workspace()),
        )
        state.workspace = resolved.path

    async def _pre_stream_independent(
        self,
        user_input: str,
        state: Any,
        complexity: str | None = None,
    ) -> AsyncGenerator[StreamChunk]:
        """Independent pre-stream: thread, policy, memory, context.

        Does NOT require enrichment results.  Safe to run concurrently
        with the tier-2 enrichment LLM call.

        Args:
            user_input: User query text.
            state: Mutable RunnerState.
            complexity: Override complexity (when known from intent classification).
                Falls back to state.intent_classification.task_complexity or "medium".
        """
        self._ensure_runner_state_workspace(state)

        from soothe.protocols.durability import ThreadMetadata

        from ._types import generate_thread_id

        if complexity is None:
            complexity = (
                state.intent_classification.task_complexity
                if state.intent_classification
                else "medium"
            )

        requested_thread_id = state.thread_id
        try:
            thread_info = None
            if requested_thread_id:
                thread_info = await self._durability.resume_thread(requested_thread_id)
                yield _custom(
                    LoopCreatedEvent(
                        loop_id=thread_info.thread_id, thread_id=thread_info.thread_id
                    ).to_dict()
                )
            else:
                thread_info = await self._durability.create_thread(
                    ThreadMetadata(policy_profile=self._config.agent.protocols.policy.profile),
                )
                yield _custom(
                    LoopCreatedEvent(
                        loop_id=thread_info.thread_id, thread_id=thread_info.thread_id
                    ).to_dict()
                )
            state.thread_id = thread_info.thread_id
        except KeyError:
            logger.debug("Thread resume failed, creating a new thread", exc_info=True)
            try:
                thread_info = await self._durability.create_thread(
                    ThreadMetadata(policy_profile=self._config.agent.protocols.policy.profile),
                )
                yield _custom(
                    LoopCreatedEvent(
                        loop_id=thread_info.thread_id, thread_id=thread_info.thread_id
                    ).to_dict()
                )
                state.thread_id = thread_info.thread_id
            except Exception:
                logger.debug("Thread creation failed after resume fallback", exc_info=True)
        except Exception:
            logger.debug("Thread creation failed, using generated ID", exc_info=True)

        if not state.thread_id:
            state.thread_id = requested_thread_id or generate_thread_id()

        store = self._ensure_artifact_store(state)
        if store and not store.manifest.query:
            store._manifest.query = user_input[:200]
            store.save_manifest()

        if requested_thread_id:
            await self._try_recover_checkpoint(state)

        protocols = self.protocol_summary()
        yield _custom(
            LoopStartedEvent(
                loop_id=state.thread_id, thread_id=state.thread_id, protocols=protocols
            ).to_dict()
        )

        if self._policy:
            try:
                from soothe.protocols.policy import PermissionSet

                decision = self._policy.check(
                    ActionRequest(action_type="user_request", tool_name=None, tool_args={}),
                    PolicyContext(
                        active_permissions=PermissionSet(frozenset()),
                        scope_id=state.thread_id,
                    ),
                )
                logger.debug("Policy checked: user_request → %s", decision.verdict)
                if decision.verdict == "deny":
                    logger.info("Policy denied: user_request | Reason: %s", decision.reason)
                    return
            except Exception:
                logger.debug("Policy check failed", exc_info=True)

        skip_memory_for_simple = getattr(
            self._config.agent.loop, "skip_memory_recall_for_simple", True
        )
        should_run_memory = (not skip_memory_for_simple) or complexity in (
            "medium",
            "complex",
        )

        if should_run_memory:
            if complexity in ("medium", "complex"):
                memory_items, _ = await self._pre_stream_parallel_memory_context(
                    user_input, complexity
                )

                state.recalled_memories = memory_items

                if memory_items:
                    logger.debug(
                        "Memory recalled: %d items | Query: %s", len(memory_items), user_input[:50]
                    )
            elif self._memory:
                try:
                    items = await self._memory.recall(user_input, limit=5)
                    state.recalled_memories = items
                    if items:
                        logger.debug(
                            "Memory recalled: %d items | Query: %s", len(items), user_input[:50]
                        )
                except Exception:
                    logger.debug("Memory recall failed", exc_info=True)

        # Collect context for system prompt XML injection (RFC-104)
        if complexity in ("medium", "complex"):
            await self._collect_context_for_injection(state)

    async def _pre_stream_planning(
        self,
        user_input: str,
        state: Any,
    ) -> AsyncGenerator[StreamChunk]:
        """Planning phase of pre-stream.  Requires enrichment (template_intent) in state.

        Must be called after tier-2 enrichment completes and
        ``state.intent_classification`` is populated.
        """
        if self._planner:
            try:
                capabilities = [name for name, cfg in self._config.subagents.items() if cfg.enabled]
                context = PlanContext(
                    recent_messages=[user_input],
                    available_capabilities=capabilities,
                    completed_steps=[],
                    routing_classification=state.intent_classification.to_routing_classification()
                    if state.intent_classification
                    else None,
                    workspace=state.workspace,  # Pass workspace for planning context
                    thread_id=getattr(state, "thread_id", None),
                )

                plan = await self._planner.create_plan(user_input, context)

                # Assign plan ID (P_1, P_2, etc.)
                # For agentic mode without goal engine, use thread-based counter
                if hasattr(state, "thread_id") and state.thread_id:
                    # Use a simple counter stored in state
                    if not hasattr(state, "_plan_count"):
                        state._plan_count = 0
                    state._plan_count += 1
                    plan.id = f"P_{state._plan_count}"

                state.plan = plan
                self._current_plan = plan  # mirror for CLI / current_plan property (IG-110)
                yield _custom(
                    PlanCreatedEvent(
                        plan_id=plan.id,
                        goal=_validate_goal(plan.goal, user_input),
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

    # -- post-stream --------------------------------------------------------

    # -- internal helpers ---------------------------------------------------

    async def _collect_context_for_injection(self, state: Any) -> None:
        """Collect context for system prompt XML injection (RFC-104).

        Gathers workspace, thread context, and protocol summary
        for injection into system prompt via SOOTHE_ XML tags.

        Args:
            state: Mutable RunnerState to attach context to.
        """
        from soothe.foundation.workspace import FrameworkFilesystem

        # Prefer ContextVar (WorkspaceContextMiddleware); else RunnerState (IG-116 / RFC-104).
        workspace_path: Path | None = FrameworkFilesystem.get_current_workspace()
        if workspace_path is None and getattr(state, "workspace", None):
            # Sync filesystem resolution; local path only (RFC-104 backfill).
            workspace_path = Path(str(state.workspace)).expanduser().resolve()  # noqa: ASYNC240

        if workspace_path:
            state.workspace = str(workspace_path)

        # Thread context
        state.thread_context = {
            "thread_id": state.thread_id,
            "active_goals": getattr(state, "active_goals", []),
            "conversation_turns": len(state.seen_message_ids)
            if hasattr(state, "seen_message_ids")
            else 0,
            "current_plan": str(state.plan)[:100]
            if hasattr(state, "plan") and state.plan
            else None,
        }

        # Protocol summary
        memory_stats = None
        if self._memory and hasattr(state, "recalled_memories"):
            memory_stats = f"{len(state.recalled_memories or [])} recalled"

        state.protocol_summary = {
            "memory": {"type": type(self._memory).__name__, "stats": memory_stats}
            if self._memory
            else None,
            "planner": {"type": type(self._planner).__name__} if self._planner else None,
            "policy": {"type": type(self._policy).__name__} if self._policy else None,
        }


# IG-273: ``generate_goal_completion_from_checkpoint`` (previously defined here)
# was removed because no code path invoked it. Goal completion synthesis is
# driven through ``StrangeLoop._run_goal_completion_synthesis`` using the live
# thread messages, not a post-hoc checkpoint synthesis helper.
