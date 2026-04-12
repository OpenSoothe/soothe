"""Query execution lifecycle for the daemon (IG-110).

Owns streaming, cancellation, and per-thread logging hooks. Uses
``SootheRunner`` public APIs only (no direct ``_durability`` access from
handlers).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Any

from soothe.core.event_catalog import ERROR
from soothe.core.workspace_resolution import resolve_workspace_for_stream
from soothe.foundation import extract_text_from_ai_message, strip_internal_tags
from soothe.logging import ThreadLogger

logger = logging.getLogger(__name__)

_STREAM_CHUNK_LENGTH = 3
_MSG_PAIR_LENGTH = 2


class QueryEngine:
    """Runs ``SootheRunner.astream`` and manages cancel/ownership for the daemon."""

    def __init__(self, daemon: Any) -> None:
        """Attach to the running ``SootheDaemon`` instance (expects ``_runner`` after ``start()``)."""
        self._daemon = daemon

    def _workspace_str_for_thread(self, thread_id: str) -> str:
        """Workspace path for ``runner.astream`` via unified resolution (IG-116)."""
        d = self._daemon
        return resolve_workspace_for_stream(
            thread_workspace=d._thread_registry.get_workspace(thread_id),
            installation_default=d._daemon_workspace,
            config_workspace_dir=d._config.workspace_dir,
        ).path

    async def run_query(
        self,
        text: str,
        *,
        autonomous: bool = False,
        max_iterations: int | None = None,
        subagent: str | None = None,
        client_id: str | None = None,
    ) -> None:
        """Stream a query through ``SootheRunner`` and broadcast events."""
        d = self._daemon
        multi_threading_enabled = getattr(d._config.daemon, "multi_threading_enabled", False)

        if multi_threading_enabled and d._thread_executor:
            await self.run_query_multithreaded(
                text,
                autonomous=autonomous,
                max_iterations=max_iterations,
                subagent=subagent,
                client_id=client_id,
            )
            return

        thread_id = await self.ensure_active_thread_id()

        st = d._thread_registry.get(thread_id)
        if st and st.is_draft:
            thread_info = await d._runner.create_persisted_thread(thread_id=st.thread_id)
            logger.info("Persisted draft thread %s", thread_info.thread_id)
            st.is_draft = False

        if not d._thread_logger or d._thread_logger._thread_id != thread_id:
            d._thread_logger = ThreadLogger(
                thread_id=thread_id,
                retention_days=d._config.logging.thread_logging.retention_days,
                max_size_mb=d._config.logging.thread_logging.max_size_mb,
            )

        if d._thread_logger:
            d._thread_logger.log_user_input(text)

        await d._runner.touch_thread_activity_timestamp(thread_id)

        # Add to global cross-thread input history
        if d._global_history:
            metadata = {
                "workspace": str(d._thread_registry.get_workspace(thread_id) or Path.cwd()),
                "autonomous": autonomous,
                "subagent": subagent,
            }
            d._global_history.add(text, thread_id=thread_id, metadata=metadata)

        query_state_lock = getattr(d, "_query_state_lock", None)
        if query_state_lock:
            async with query_state_lock:
                d._query_running = True
                d._active_threads[thread_id] = None
        else:
            d._query_running = True

        if client_id:
            await d._session_manager.claim_thread_ownership(client_id, thread_id)
            await d._session_manager.subscribe_thread(client_id, thread_id)

        await d._broadcast({"type": "status", "state": "running", "thread_id": thread_id})

        full_response: list[str] = []

        async def _run_stream() -> None:
            chunk_count = 0
            timeout_minutes = d._config.daemon.max_query_duration_minutes
            timeout_enabled = timeout_minutes > 0
            timeout_seconds = timeout_minutes * 60 if timeout_enabled else None
            warning_threshold = timeout_seconds * 0.8 if timeout_enabled else None
            start_time = asyncio.get_event_loop().time() if timeout_enabled else None
            warning_sent = False

            try:
                stream_kwargs: dict[str, Any] = {
                    "thread_id": thread_id,
                    "workspace": self._workspace_str_for_thread(thread_id),
                }
                if autonomous:
                    stream_kwargs["autonomous"] = True
                    if max_iterations is not None:
                        stream_kwargs["max_iterations"] = max_iterations
                if subagent is not None:
                    stream_kwargs["subagent"] = subagent

                # Wrap streaming with timeout if configured
                if timeout_enabled:
                    async with asyncio.timeout(timeout_seconds):
                        async for chunk in d._runner.astream(text, **stream_kwargs):
                            # IG-157: Check for task cancellation from cancel_current_query()
                            if d._current_query_task and d._current_query_task.done():
                                logger.info("Stream loop detected cancelled task, stopping")
                                break

                            chunk_count += 1

                            # Check for warning threshold (80% of timeout)
                            if not warning_sent and warning_threshold:
                                elapsed = asyncio.get_event_loop().time() - start_time
                                if elapsed >= warning_threshold:
                                    warning_sent = True
                                    remaining = timeout_seconds - elapsed
                                    logger.warning(
                                        "Query approaching timeout for thread %s (%.1fs remaining)",
                                        thread_id,
                                        remaining,
                                    )
                                    await d._broadcast(
                                        {
                                            "type": "event",
                                            "thread_id": thread_id,
                                            "namespace": [],
                                            "mode": "custom",
                                            "data": {
                                                "type": "query_timeout_warning",
                                                "message": f"Query will timeout in {remaining:.0f} seconds",
                                                "remaining_seconds": remaining,
                                            },
                                        }
                                    )

                            # Process chunk
                            if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LENGTH:
                                logger.debug("Skipping invalid chunk #%d: type=%s", chunk_count, type(chunk).__name__)
                                continue
                            namespace, mode, data = chunk
                            logger.debug("Received chunk #%d: namespace=%s, mode=%s", chunk_count, namespace, mode)

                            d._thread_logger.log(tuple(namespace), mode, data)

                            if (
                                not namespace
                                and mode == "custom"
                                and isinstance(data, dict)
                                and (output_text := self.extract_custom_output_text(data))
                            ):
                                full_response.append(output_text)

                            is_msg_pair = isinstance(data, (tuple, list)) and len(data) == _MSG_PAIR_LENGTH
                            if not namespace and mode == "messages" and is_msg_pair:
                                msg, _metadata = data
                                full_response.extend(extract_text_from_ai_message(msg))

                            event_msg = {
                                "type": "event",
                                "thread_id": thread_id,
                                "namespace": list(namespace),
                                "mode": mode,
                                "data": data,
                            }
                            await d._broadcast(event_msg)
                        logger.debug("runner.astream() completed, total chunks: %d", chunk_count)
                else:
                    # No timeout - original behavior
                    async for chunk in d._runner.astream(text, **stream_kwargs):
                        # IG-157: Check for task cancellation from cancel_current_query()
                        if d._current_query_task and d._current_query_task.done():
                            logger.info("Stream loop detected cancelled task, stopping")
                            break

                        chunk_count += 1
                        if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LENGTH:
                            logger.debug("Skipping invalid chunk #%d: type=%s", chunk_count, type(chunk).__name__)
                            continue
                        namespace, mode, data = chunk
                        logger.debug("Received chunk #%d: namespace=%s, mode=%s", chunk_count, namespace, mode)

                        d._thread_logger.log(tuple(namespace), mode, data)

                        if (
                            not namespace
                            and mode == "custom"
                            and isinstance(data, dict)
                            and (output_text := self.extract_custom_output_text(data))
                        ):
                            full_response.append(output_text)

                        is_msg_pair = isinstance(data, (tuple, list)) and len(data) == _MSG_PAIR_LENGTH
                        if not namespace and mode == "messages" and is_msg_pair:
                            msg, _metadata = data
                            full_response.extend(extract_text_from_ai_message(msg))

                        event_msg = {
                            "type": "event",
                            "thread_id": thread_id,
                            "namespace": list(namespace),
                            "mode": mode,
                            "data": data,
                        }
                        await d._broadcast(event_msg)
                    logger.debug("runner.astream() completed, total chunks: %d", chunk_count)

            except TimeoutError:
                # Query exceeded maximum duration
                logger.warning(
                    "Query exceeded %d minute timeout for thread %s",
                    timeout_minutes,
                    thread_id,
                )
                from soothe.core import FrameworkFilesystem

                FrameworkFilesystem.clear_current_workspace()

                # Cancel the running query
                if d._current_query_task:
                    d._current_query_task.cancel()

                # Broadcast timeout error to client
                await d._broadcast(
                    {
                        "type": "event",
                        "thread_id": thread_id,
                        "namespace": [],
                        "mode": "custom",
                        "data": {
                            "type": ERROR,
                            "error": f"Query cancelled after {timeout_minutes} minute timeout",
                            "timeout_minutes": timeout_minutes,
                        },
                    }
                )
            except asyncio.CancelledError:
                logger.info("Query cancelled by user")
                from soothe.core import FrameworkFilesystem

                FrameworkFilesystem.clear_current_workspace()
                await d._broadcast(
                    {
                        "type": "event",
                        "thread_id": thread_id,
                        "namespace": [],
                        "mode": "custom",
                        "data": {"type": ERROR, "error": "Query cancelled by user"},
                    }
                )
                raise
            except Exception as exc:
                logger.exception("Daemon query error")
                from soothe.utils.error_format import emit_error_event

                await d._broadcast(
                    {
                        "type": "event",
                        "thread_id": thread_id,
                        "namespace": [],
                        "mode": "custom",
                        "data": emit_error_event(exc),
                    }
                )
            finally:
                d._query_running = False
                d._active_threads.pop(thread_id, None)

        try:
            task = asyncio.create_task(_run_stream())
            d._current_query_task = task
            d._active_threads[thread_id] = task
            await task
        except asyncio.CancelledError:
            logger.info("Query task cancelled")
            d._runner.set_current_thread_id(None)
        finally:
            d._current_query_task = None
            if client_id:
                await d._session_manager.release_thread_ownership(client_id)

        final_thread_id = d._runner.current_thread_id or ""
        if final_thread_id and final_thread_id != thread_id:
            d._thread_logger = ThreadLogger(
                thread_id=final_thread_id,
                retention_days=d._config.logging.thread_logging.retention_days,
                max_size_mb=d._config.logging.thread_logging.max_size_mb,
            )
            d._thread_logger.log_user_input(text)

        if full_response:
            d._thread_logger.log_assistant_response("".join(full_response))

        if final_thread_id:
            await d._runner.touch_thread_activity_timestamp(final_thread_id)

        completion_thread_id = thread_id or final_thread_id
        await d._broadcast({"type": "status", "state": "idle", "thread_id": completion_thread_id})

    async def run_query_multithreaded(
        self,
        text: str,
        *,
        autonomous: bool = False,
        max_iterations: int | None = None,
        subagent: str | None = None,
        client_id: str | None = None,
    ) -> None:
        """Execute query using ``ThreadExecutor``.

        Wraps the streaming work in its own ``asyncio.Task`` so that
        cancellation targets the query — **not** the ``_input_loop`` task.
        """
        d = self._daemon
        thread_id = await self.ensure_active_thread_id()

        st = d._thread_registry.get(thread_id)
        if st and st.is_draft:
            await d._runner.create_persisted_thread(thread_id=st.thread_id)
            logger.info("Persisted draft thread %s", st.thread_id)
            st.is_draft = False

        if not d._thread_logger or d._thread_logger._thread_id != thread_id:
            d._thread_logger = ThreadLogger(
                thread_id=thread_id,
                retention_days=d._config.logging.thread_logging.retention_days,
                max_size_mb=d._config.logging.thread_logging.max_size_mb,
            )

        if d._thread_logger:
            d._thread_logger.log_user_input(text)

        await d._runner.touch_thread_activity_timestamp(thread_id)

        # Add to global cross-thread input history
        if d._global_history:
            metadata = {
                "workspace": str(d._thread_registry.get_workspace(thread_id) or Path.cwd()),
                "autonomous": autonomous,
                "subagent": subagent,
            }
            d._global_history.add(text, thread_id=thread_id, metadata=metadata)

        if client_id:
            await d._session_manager.claim_thread_ownership(client_id, thread_id)
            await d._session_manager.subscribe_thread(client_id, thread_id)

        d._query_running = True
        await d._broadcast({"type": "status", "state": "running", "thread_id": thread_id})

        full_response: list[str] = []

        async def _run_stream() -> None:
            try:
                stream_kwargs: dict[str, Any] = {"workspace": self._workspace_str_for_thread(thread_id)}
                if autonomous:
                    stream_kwargs["autonomous"] = True
                    if max_iterations is not None:
                        stream_kwargs["max_iterations"] = max_iterations
                if subagent is not None:
                    stream_kwargs["subagent"] = subagent

                stream_tuple_length = 3
                msg_pair_length = 2
                async for chunk in d._thread_executor.execute_thread(thread_id, text, **stream_kwargs):
                    # IG-157: Check for task cancellation from cancel_current_query()
                    if d._current_query_task and d._current_query_task.done():
                        logger.info("Multithreaded stream loop detected cancelled task, stopping")
                        break

                    if not isinstance(chunk, tuple) or len(chunk) != stream_tuple_length:
                        continue
                    namespace, mode, data = chunk

                    d._thread_logger.log(tuple(namespace), mode, data)

                    if (
                        not namespace
                        and mode == "custom"
                        and isinstance(data, dict)
                        and (output_text := self.extract_custom_output_text(data))
                    ):
                        full_response.append(output_text)

                    is_msg_pair = isinstance(data, (tuple, list)) and len(data) == msg_pair_length
                    if not namespace and mode == "messages" and is_msg_pair:
                        msg, _metadata = data
                        full_response.extend(extract_text_from_ai_message(msg))

                    event_msg = {
                        "type": "event",
                        "thread_id": thread_id,
                        "namespace": list(namespace),
                        "mode": mode,
                        "data": data,
                    }
                    await d._broadcast(event_msg)

            except asyncio.CancelledError:
                logger.info("Query cancelled by user in thread %s", thread_id)
                from soothe.core import FrameworkFilesystem

                FrameworkFilesystem.clear_current_workspace()
                await d._broadcast(
                    {
                        "type": "event",
                        "thread_id": thread_id,
                        "namespace": [],
                        "mode": "custom",
                        "data": {"type": ERROR, "error": f"Query cancelled in thread {thread_id}"},
                    }
                )
                raise
            except Exception as exc:
                logger.exception("Multi-threaded query error in thread %s", thread_id)
                from soothe.utils.error_format import emit_error_event

                await d._broadcast(
                    {
                        "type": "event",
                        "thread_id": thread_id,
                        "namespace": [],
                        "mode": "custom",
                        "data": emit_error_event(exc),
                    }
                )
            finally:
                d._query_running = False
                d._active_threads.pop(thread_id, None)

        try:
            task = asyncio.create_task(_run_stream())
            d._current_query_task = task
            d._active_threads[thread_id] = task
            await task
        except asyncio.CancelledError:
            logger.info("Query task cancelled for thread %s", thread_id)
            d._runner.set_current_thread_id(None)
        finally:
            d._current_query_task = None
            if client_id:
                await d._session_manager.release_thread_ownership(client_id)

        final_thread_id = d._runner.current_thread_id or ""
        if final_thread_id and final_thread_id != thread_id:
            d._thread_logger = ThreadLogger(
                thread_id=final_thread_id,
                retention_days=d._config.logging.thread_logging.retention_days,
                max_size_mb=d._config.logging.thread_logging.max_size_mb,
            )
            d._thread_logger.log_user_input(text)

        if full_response:
            d._thread_logger.log_assistant_response("".join(full_response))

        if final_thread_id:
            await d._runner.touch_thread_activity_timestamp(final_thread_id)

        completion_thread_id = thread_id or final_thread_id
        await d._broadcast({"type": "status", "state": "idle", "thread_id": completion_thread_id})

    async def cancel_current_query(self) -> None:
        """Cancel the currently running query if any."""
        d = self._daemon
        active_thread_tasks = bool(
            d._active_threads and any(t is not None and not t.done() for t in d._active_threads.values())
        )
        has_current_task = bool(d._current_query_task and not d._current_query_task.done())
        # Rely on concrete tasks, not only _query_running (avoids races / stale flags).
        if not active_thread_tasks and not has_current_task:
            return

        cancelled_any = False

        if d._active_threads:
            thread_ids = list(d._active_threads.keys())
            for tid in thread_ids:
                task = d._active_threads.pop(tid, None)
                if task and not task.done():
                    task.cancel()
                    logger.info("Cancelling thread %s (multithreaded mode)", tid)
                    try:
                        # IG-157: Wait for task to actually stop
                        await asyncio.wait_for(task, timeout=2.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        logger.warning("Thread %s did not stop cleanly within 2s", tid)
                    cancelled_any = True
                    d._runner.set_current_thread_id(None)

            if cancelled_any:
                d._query_running = False
                d._current_query_task = None

        if not cancelled_any and d._current_query_task and not d._current_query_task.done():
            logger.info("Cancelling current query task (single-threaded mode)")
            d._current_query_task.cancel()
            try:
                # IG-157: Wait for task to actually stop with timeout
                await asyncio.wait_for(d._current_query_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                logger.warning("Query task did not stop cleanly within 2s")

            d._query_running = False
            d._current_query_task = None

            d._runner.set_current_thread_id(None)
            cancelled_any = True

        if cancelled_any:
            await d._broadcast(
                {
                    "type": "command_response",
                    "content": "[green]Query cancelled successfully.[/green]",
                }
            )
            # IG-157: Broadcast idle status immediately after cancel
            final_thread_id = d._runner.current_thread_id or ""
            await d._broadcast({"type": "status", "state": "idle", "thread_id": final_thread_id})

    async def cancel_thread(self, thread_id: str) -> None:
        """Cancel a specific thread's execution."""
        d = self._daemon
        query_state_lock = getattr(d, "_query_state_lock", None)
        if query_state_lock:
            async with query_state_lock:
                await self._cancel_thread_locked(thread_id)
        else:
            await self._cancel_thread_locked(thread_id)

    async def _cancel_thread_locked(self, thread_id: str) -> None:
        d = self._daemon
        if thread_id in d._active_threads:
            task = d._active_threads.pop(thread_id, None)
            if task and not task.done():
                task.cancel()
                logger.info("Cancelled thread %s", thread_id)
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            d._runner.set_current_thread_id(None)
            d._query_running = False
            d._current_query_task = None
            await d._broadcast(
                {
                    "type": "status",
                    "state": "idle",
                    "thread_id": thread_id,
                    "cancelled": True,
                }
            )
            return

        if d._current_query_task and not d._current_query_task.done():
            current_thread = d._runner.current_thread_id if d._runner else None
            if current_thread == thread_id:
                d._current_query_task.cancel()
                logger.info("Cancelled thread %s (legacy single-threaded mode)", thread_id)
                with contextlib.suppress(asyncio.CancelledError):
                    await d._current_query_task
                d._runner.set_current_thread_id(None)
                d._query_running = False
                d._current_query_task = None
                await d._broadcast({"type": "status", "state": "idle", "thread_id": thread_id})
                return

        logger.debug("Thread %s not found or already complete", thread_id)
        if d._runner and d._runner.current_thread_id == thread_id:
            d._runner.set_current_thread_id(None)

    async def ensure_active_thread_id(self) -> str:
        """Ensure current query runs with a concrete thread ID."""
        d = self._daemon
        current = str(d._runner.current_thread_id or "").strip()
        if current:
            return current

        thread_info = await d._runner.create_persisted_thread()
        tid = thread_info.thread_id
        d._runner.set_current_thread_id(tid)
        d._thread_registry.ensure(tid, is_draft=False)
        d._thread_registry.set_workspace(tid, Path(d._daemon_workspace))
        return tid

    @staticmethod
    def extract_custom_output_text(data: dict[str, Any]) -> str | None:
        """Extract assistant-visible output text from custom protocol events."""
        from soothe.core.event_catalog import CHITCHAT_RESPONSE, FINAL_REPORT

        event_type = str(data.get("type", ""))
        if event_type == CHITCHAT_RESPONSE:
            content = data.get("content", "")
            cleaned = strip_internal_tags(str(content))
            return cleaned or None
        if event_type == FINAL_REPORT:
            content = data.get("summary", "")
            cleaned = strip_internal_tags(str(content))
            return cleaned or None
        return None
