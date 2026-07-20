"""Phase orchestration mixin for SootheRunner (chitchat and checkpointer helpers).

Extracted from ``runner.py`` to keep the main module focused on orchestration.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe_sdk.core.exceptions import ConfigurationError

from soothe.foundation.sloop.utils.messages import loop_assistant_messages_chunk

from ._runner_shared import StreamChunk

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


logger = logging.getLogger(__name__)


class PhasesMixin:
    """Chitchat fast path and LangGraph checkpointer initialization.

    Mixed into ``SootheRunner`` -- all ``self.*`` attributes are defined
    on the concrete class.
    """

    # -- chitchat fast path (piggybacked intake response) ------------------

    async def _run_chitchat(
        self,
        user_input: str,
        thread_id: str,
        *,
        chitchat_response: str,
        context_engine: Any | None = None,
        ce_goal_id: str | None = None,
        loop_id: str | None = None,
        defer_persistence: bool = False,
    ) -> AsyncGenerator[StreamChunk]:
        """Fast path for chitchat intake: emit piggybacked response directly.

        When ``defer_persistence`` is true, only the wire response is emitted; the
        caller must invoke ``_save_chitchat_to_state`` after the StrangeLoop graph
        finishes so checkpoint finalize does not race ``run_with_progress`` teardown.
        """
        main_thread_id = (loop_id or self._client_loop_id_for_stream or thread_id or "").strip()
        if not main_thread_id:
            main_thread_id = thread_id

        response = (chitchat_response or "").strip()

        logger.info("Chitchat: %s (main_thread=%s)", user_input[:50], main_thread_id)

        yield loop_assistant_messages_chunk(
            content=response,
            phase="chitchat",
            thread_id=main_thread_id,
        )

        if defer_persistence:
            return

        try:
            await self._save_chitchat_to_state(
                user_input,
                response,
                main_thread_id,
                context_engine=context_engine,
                ce_goal_id=ce_goal_id,
                loop_id=main_thread_id,
            )
        except Exception:
            logger.warning(
                "Chitchat persistence/finalize failed (loop=%s)",
                main_thread_id,
                exc_info=True,
            )

    async def _save_chitchat_to_state(
        self,
        query: str,
        response: str,
        main_thread_id: str,
        *,
        context_engine: Any | None = None,
        ce_goal_id: str | None = None,
        loop_id: str | None = None,
    ) -> None:
        """Persist chitchat Human+AI pair to ledger and finalize loop checkpoint."""
        await self._save_chitchat_to_ledger(
            query,
            response,
            main_thread_id,
            context_engine=context_engine,
        )
        await self._finalize_chitchat_loop(
            loop_id or main_thread_id,
            response=response,
            context_engine=context_engine,
            ce_goal_id=ce_goal_id,
        )

    async def _save_chitchat_to_ledger(
        self,
        query: str,
        response: str,
        main_thread_id: str,
        *,
        context_engine: Any | None = None,
    ) -> None:
        """Persist chitchat Human+AI pair to the loop ContextEngine ledger."""
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
                human = LoopHumanMessage(
                    content=query,
                    thread_id=main_thread_id,
                    phase="chitchat",
                )
                ai = LoopAIMessage(
                    content=answer,
                    thread_id=main_thread_id,
                    phase="chitchat",
                )
                _record_ledger_message(context_engine, human, "chitchat")
                _record_ledger_message(context_engine, ai, "chitchat")
                await context_engine.save()
                logger.debug(
                    "Chitchat exchange saved to active loop ledger (loop=%s)",
                    main_thread_id,
                )
                return
            except Exception:
                logger.debug("Failed to save chitchat to active loop ledger", exc_info=True)

        loop_id = (main_thread_id or "").strip()
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
            human = LoopHumanMessage(content=query, thread_id=main_thread_id, phase="chitchat")
            ai = LoopAIMessage(content=answer, thread_id=main_thread_id, phase="chitchat")
            _record_ledger_message(ce, human, "chitchat")
            _record_ledger_message(ce, ai, "chitchat")
            await ce.save()
            logger.debug("Chitchat exchange saved to loop ledger for loop %s", loop_id)
        except Exception:
            logger.debug("Failed to save chitchat to loop ledger", exc_info=True)

    async def _finalize_chitchat_loop(
        self,
        loop_id: str,
        *,
        response: str,
        context_engine: Any | None = None,
        ce_goal_id: str | None = None,
    ) -> None:
        """Mark the active StrangeLoop goal complete and return checkpoint to idle."""
        loop_id = (loop_id or "").strip()
        if not loop_id:
            return

        try:
            from soothe.foundation.sloop.state.sloop_manager import StrangeLoopStateManager
            from soothe.foundation.sloop.utils.structural_continuation import (
                chitchat_may_finalize_checkpoint,
            )

            shared_pool = await self.get_sloop_shared_pool()
            sm = StrangeLoopStateManager(
                config=self._config,
                loop_id=loop_id,
                shared_pool=shared_pool,
            )
            try:
                checkpoint = await sm.load()
                if checkpoint is None:
                    return
                if not chitchat_may_finalize_checkpoint(checkpoint):
                    logger.info(
                        "Chitchat finalize skipped for loop %s (status=%s)",
                        loop_id,
                        checkpoint.status,
                    )
                    return
                idx = checkpoint.current_goal_index
                if idx < 0 or idx >= len(checkpoint.goal_history):
                    return
                goal_record = checkpoint.goal_history[idx]
                if context_engine is not None and ce_goal_id:
                    try:
                        await context_engine.finalize_goal(ce_goal_id, status="completed")
                    except Exception:
                        logger.debug(
                            "CE finalize_goal failed for chitchat fast path",
                            exc_info=True,
                        )
                await sm.finalize_goal(goal_record, response)
            finally:
                await sm.close()
        except Exception:
            logger.warning(
                "StrangeLoop finalize failed for chitchat (loop=%s)",
                loop_id,
                exc_info=True,
            )

    # -- LangGraph stream with interrupt auto-resume -------------------------

    async def _ensure_checkpointer_initialized(self) -> None:
        """Lazily initialize the async checkpointer (AsyncSqliteSaver / AsyncPostgresSaver).

        The checkpointer is created from ``self._checkpointer_pool`` and replaces
        the placeholder on ``self._core_agent.graph``.  Must be called before
        any ``core_agent.astream()`` that needs persistent thread state.

        Raises ConfigurationError if checkpointer initialization fails.
        """
        from soothe.foundation.coreagent.lazy import LazyCoreAgent

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
            # Agent doesn't use LangGraph checkpointer
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
