"""Query execution lifecycle for the daemon (IG-110).

Owns streaming, cancellation, and per-thread logging hooks. Uses
``SootheRunner`` public APIs only (no direct ``_durability`` access from
handlers).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from soothe.core.events import ERROR
from soothe.core.workspace import resolve_workspace_for_stream
from soothe_daemon.image_understanding import enrich_user_text_with_vision
from soothe.foundation import extract_text_from_ai_message
from soothe.logging import ThreadLogger
from soothe.utils.error_format import emit_error_event

logger = logging.getLogger(__name__)

_STREAM_CHUNK_LENGTH = 3
_MSG_PAIR_LENGTH = 2


class QueryEngine:
    """Runs ``SootheRunner.astream`` and manages cancel/ownership for the daemon.

    IG-408: Locals named ``thread_id`` in this module are LangGraph **checkpoint ids**
    (``configurable.thread_id``). Client-visible scope is always ``loop_id`` /
    ``effective_loop_id``; ``_loop_scoped_client_message`` strips stray ``thread_id``
    keys from outbound frames.
    """

    def __init__(self, daemon: Any) -> None:
        """Attach to the running ``SootheDaemon`` instance (expects ``_runner_factory`` after ``start()``)."""
        self._daemon = daemon
        # RFC-221: per-loop runner instances keyed by loop_id
        self._active_runners: dict[str, Any] = {}

    @staticmethod
    def _loop_scoped_client_message(loop_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Build a client-visible frame: always ``loop_id``, never CoreAgent ``thread_id``."""
        out = dict(payload)
        out["loop_id"] = str(loop_id).strip()
        out.pop("thread_id", None)
        return out

    async def _enrich_with_vision_throttled(
        self,
        config: Any,
        text: str,
        attachments: list[dict[str, str]],
        *,
        session_id: str | None = None,
    ) -> str:
        """Run vision preflight under daemon-wide concurrency cap when configured."""
        d = self._daemon
        sem = getattr(d, "_vision_preflight_semaphore", None)
        if sem is None:
            return await enrich_user_text_with_vision(
                config, text, attachments, session_id=session_id
            )
        async with sem:
            return await enrich_user_text_with_vision(
                config, text, attachments, session_id=session_id
            )

    def _workspace_str_for_thread(self, thread_id: str) -> str:
        """Workspace path for ``runner.astream`` via unified resolution (IG-116)."""
        d = self._daemon
        return resolve_workspace_for_stream(
            thread_workspace=d._thread_registry.get_workspace(thread_id),
            installation_default=d._daemon_workspace,
            config_workspace_dir=d._config.workspace_dir,
        ).path

    async def _resolve_query_checkpoint_thread_id(
        self,
        *,
        checkpoint_thread_id: str | None,
        client_id: str | None,
    ) -> str:
        """Pick LangGraph checkpoint id for this query.

        When ``loop_input`` already ran ``bind_execution_thread_for_loop``, callers pass
        that checkpoint here so workspace/registry state matches the subprocess run.
        Otherwise fall back to the utility runner singleton + ``ensure_active_*``.
        """
        d = self._daemon
        tid = str(checkpoint_thread_id or "").strip()
        if tid:
            d._runner.set_current_thread_id(tid)
            return tid
        thread_id = str(d._runner.current_thread_id or "").strip()
        if not thread_id:
            thread_id = await self.ensure_active_checkpoint_thread_id(client_id)
        return thread_id

    async def run_query(
        self,
        text: str,
        *,
        loop_id: str | None = None,
        autonomous: bool = False,
        max_iterations: int | None = None,
        preferred_subagent: str | None = None,
        client_id: str | None = None,
        interactive: bool = False,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        attachments: list[dict[str, str]] | None = None,
        checkpoint_thread_id: str | None = None,
        intent_hint: str | None = None,
    ) -> None:
        """Stream a query through subprocess workers and broadcast events."""
        d = self._daemon

        thread_id = await self._resolve_query_checkpoint_thread_id(
            checkpoint_thread_id=checkpoint_thread_id,
            client_id=client_id,
        )

        lid_in = str(loop_id or "").strip()
        if client_id and not lid_in:
            logger.warning(
                "[Query] Rejecting client %s: missing loop_id (work must be scoped to a loop)",
                client_id[:8],
            )
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "NO_LOOP_ID",
                    "message": "loop_id is required; subscribe to a loop before sending input",
                },
            )
            return

        effective_loop_id = (
            lid_in or str(d._thread_registry.get_thread_loop(thread_id) or "").strip()
        )

        st = d._thread_registry.get(thread_id)
        if st and st.is_draft:
            thread_info = await d._runner.create_persisted_thread(thread_id=st.thread_id)
            logger.info("Persisted draft thread %s", thread_info.thread_id)
            st.is_draft = False

        if not d._thread_logger or d._thread_logger._thread_id != thread_id:
            d._thread_logger = ThreadLogger(
                thread_id=thread_id,
                retention_days=d._config.observability.thread_logging_retention_days,
                max_size_mb=d._config.observability.thread_logging_max_size_mb,
            )
        thread_logger = d._thread_logger  # local ref — safe against concurrent overwrites

        # IG-054: Capacity check before vision preflight (IG-327) to avoid wasted image API calls.
        # Check is done outside the lock to avoid holding it during awaits; the insert is
        # protected by _query_state_lock (Bug 4.4).
        max_concurrent = getattr(d._daemon_config, "max_concurrent_threads", 100)
        async with d._query_state_lock:
            at_capacity = max_concurrent > 0 and len(d._active_threads) >= max_concurrent
        if at_capacity:
            logger.warning(
                "Daemon at capacity (%d/%d queries), rejecting (loop=%s checkpoint=%s)",
                len(d._active_threads),
                max_concurrent,
                effective_loop_id or "?",
                thread_id[:16] if thread_id else "?",
            )

            if effective_loop_id:
                await d._broadcast(
                    self._loop_scoped_client_message(
                        effective_loop_id,
                        {
                            "type": "event",
                            "namespace": [],
                            "mode": "custom",
                            "data": {
                                "type": ERROR,
                                "error": (
                                    f"Daemon has reached its concurrent query limit ({max_concurrent}). "
                                    "Wait for a query to finish or cancel one before starting a new one."
                                ),
                                "code": "DAEMON_BUSY",
                            },
                        },
                    )
                )
                await d._broadcast(
                    self._loop_scoped_client_message(
                        effective_loop_id,
                        {"type": "status", "state": "idle"},
                    )
                )
            if client_id:
                await d._session_manager.release_loop_ownership(client_id)
            return

        effective_text = text
        if attachments:
            try:
                effective_text = await self._enrich_with_vision_throttled(
                    d._config, text, attachments, session_id=thread_id
                )
            except Exception as exc:
                logger.exception(
                    "Vision preflight failed (loop=%s checkpoint=%s)",
                    effective_loop_id or "?",
                    thread_id[:16] if thread_id else "?",
                )
                if effective_loop_id:
                    await d._broadcast(
                        self._loop_scoped_client_message(
                            effective_loop_id,
                            {
                                "type": "event",
                                "namespace": [],
                                "mode": "custom",
                                "data": emit_error_event(exc),
                            },
                        )
                    )
                    await d._broadcast(
                        self._loop_scoped_client_message(
                            effective_loop_id,
                            {"type": "status", "state": "idle"},
                        )
                    )
                if client_id:
                    await d._session_manager.release_loop_ownership(client_id)
                return

        thread_logger.log_user_input(effective_text)

        await d._runner.touch_thread_activity_timestamp(thread_id)

        st_activity = d._thread_registry.get(thread_id)
        if st_activity:
            st_activity.last_activity = datetime.now(UTC)

        # Add to global cross-thread input history
        if d._global_history:
            metadata = {
                "workspace": str(
                    d._thread_registry.get_workspace(thread_id) or d._daemon_workspace
                ),
                "autonomous": autonomous,
                "preferred_subagent": preferred_subagent,
            }
            d._global_history.add(effective_text, thread_id=thread_id, metadata=metadata)

        # No placeholder pattern - set task directly after creation
        async with d._query_state_lock:
            d._query_running = True

        if client_id and effective_loop_id:
            await d._session_manager.claim_loop_ownership(client_id, effective_loop_id)
            subscribed = await d._session_manager.subscribe_loop(client_id, effective_loop_id)
            if not subscribed:
                logger.warning(
                    "Client %s not found for loop %s subscription - query will run without client notifications",
                    client_id[:8],
                    effective_loop_id[:8],
                )

        if effective_loop_id:
            await d._broadcast(
                self._loop_scoped_client_message(
                    effective_loop_id,
                    {"type": "status", "state": "running"},
                )
            )

        full_response: list[str] = []

        async def _run_stream() -> None:
            from soothe.core.context.model_override import (
                attach_stream_model_override,
                reset_stream_model_override,
            )

            if effective_loop_id:
                d._active_stream_loop_ids.add(effective_loop_id)  # Bug 4.3: set-based tracking
            m_clean = model.strip() if isinstance(model, str) and model.strip() else None
            override_token = attach_stream_model_override(m_clean, model_params)

            chunk_count = 0
            timeout_minutes = d._daemon_config.max_query_duration_minutes
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
                if preferred_subagent is not None:
                    stream_kwargs["preferred_subagent"] = preferred_subagent

                # All queries (interactive and non-interactive) use subprocess
                # isolation via the runner factory. Interactive HITL is supported
                # through interrupt_queue IPC on the pool worker.
                _runner_key = effective_loop_id or thread_id

                from soothe.protocols.runner import InterruptPending, LoopRunRequest

                run_request = LoopRunRequest(
                    loop_id=effective_loop_id or thread_id,
                    thread_id=thread_id,
                    user_input=effective_text,
                    workspace=stream_kwargs.get("workspace"),
                    autonomous=stream_kwargs.get("autonomous", False),
                    max_iterations=stream_kwargs.get("max_iterations"),
                    preferred_subagent=stream_kwargs.get("preferred_subagent"),
                    model=model,
                    model_params=model_params or {},
                    intent_hint=intent_hint,
                    interactive=bool(interactive and client_id and effective_loop_id),
                )
                loop_runner = d._runner_factory.create_runner(_runner_key)
                self._active_runners[_runner_key] = loop_runner

                async def _stream_chunks() -> Any:
                    async for item in loop_runner.run(run_request):
                        yield item

                async def _process_stream() -> None:
                    nonlocal chunk_count, warning_sent

                    async for chunk in _stream_chunks():
                        if d._current_query_task and d._current_query_task.done():
                            logger.info("Stream loop detected cancelled task, stopping")
                            break

                        # Handle HITL interrupt from subprocess worker
                        if isinstance(chunk, InterruptPending):
                            await self._bridge_subprocess_interrupt(
                                d, chunk, loop_runner, thread_id, client_id, effective_loop_id
                            )
                            continue

                        chunk_count += 1

                        if timeout_enabled and not warning_sent and warning_threshold:
                            elapsed = asyncio.get_event_loop().time() - start_time
                            if elapsed >= warning_threshold:
                                warning_sent = True
                                remaining = timeout_seconds - elapsed
                                logger.warning(
                                    "Query approaching timeout (loop=%s checkpoint=%s, %.1fs left)",
                                    effective_loop_id or "?",
                                    thread_id[:16] if thread_id else "?",
                                    remaining,
                                )
                                if effective_loop_id:
                                    await d._broadcast(
                                        self._loop_scoped_client_message(
                                            effective_loop_id,
                                            {
                                                "type": "event",
                                                "namespace": [],
                                                "mode": "custom",
                                                "data": {
                                                    "type": "query_timeout_warning",
                                                    "message": f"Query will timeout in {remaining:.0f} seconds",
                                                    "remaining_seconds": remaining,
                                                },
                                            },
                                        )
                                    )

                        if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LENGTH:
                            logger.debug(
                                "Skipping invalid chunk #%d: type=%s",
                                chunk_count,
                                type(chunk).__name__,
                            )
                            continue
                        namespace, mode, data = chunk

                        thread_logger.log(tuple(namespace), mode, data)

                        is_msg_pair = (
                            isinstance(data, (tuple, list)) and len(data) == _MSG_PAIR_LENGTH
                        )
                        if not namespace and mode == "messages" and is_msg_pair:
                            msg, _metadata = data
                            full_response.extend(extract_text_from_ai_message(msg))

                        if effective_loop_id:
                            event_msg = self._loop_scoped_client_message(
                                effective_loop_id,
                                {
                                    "type": "event",
                                    "namespace": list(namespace),
                                    "mode": mode,
                                    "data": data,
                                },
                            )
                            await d._broadcast(event_msg)

                    logger.debug("runner.astream() completed, total chunks: %d", chunk_count)

                if timeout_enabled:
                    async with asyncio.timeout(timeout_seconds):
                        await _process_stream()
                else:
                    await _process_stream()

            except TimeoutError:
                # Query exceeded maximum duration
                logger.warning(
                    "Query exceeded %d minute timeout (loop=%s checkpoint=%s)",
                    timeout_minutes,
                    effective_loop_id or "?",
                    thread_id[:16] if thread_id else "?",
                )
                from soothe.core import FrameworkFilesystem

                FrameworkFilesystem.clear_current_workspace()

                # Cancel the running query
                if d._current_query_task:
                    d._current_query_task.cancel()

                if effective_loop_id:
                    await d._broadcast(
                        self._loop_scoped_client_message(
                            effective_loop_id,
                            {
                                "type": "event",
                                "namespace": [],
                                "mode": "custom",
                                "data": {
                                    "type": ERROR,
                                    "error": f"Query cancelled after {timeout_minutes} minute timeout",
                                    "timeout_minutes": timeout_minutes,
                                },
                            },
                        )
                    )
            except asyncio.CancelledError:
                logger.info("Query cancelled by user")
                from soothe.core import FrameworkFilesystem

                FrameworkFilesystem.clear_current_workspace()
                raise
            except Exception as exc:
                logger.exception("Daemon query error")
                if effective_loop_id:
                    await d._broadcast(
                        self._loop_scoped_client_message(
                            effective_loop_id,
                            {
                                "type": "event",
                                "namespace": [],
                                "mode": "custom",
                                "data": emit_error_event(exc),
                            },
                        )
                    )
            finally:
                reset_stream_model_override(override_token)
                d._query_running = False
                d._active_threads.pop(thread_id, None)
                # RFC-221: tear down the subprocess runner (pool cancel_event / local SIGTERM).
                # ``cancel_loop`` may have already popped and cancelled; pop here covers
                # disconnect and other paths where no explicit cancel ran.
                loop_runner_cleanup = self._active_runners.pop(effective_loop_id or thread_id, None)
                if loop_runner_cleanup is not None:
                    try:
                        await loop_runner_cleanup.cancel()
                    except Exception:
                        logger.debug(
                            "QueryEngine: loop_runner.cancel during stream finally failed",
                            exc_info=True,
                        )
                if effective_loop_id:  # Flaw 4.8: guard against None key
                    d._pending_interrupt_responses.pop(effective_loop_id, None)
                if effective_loop_id:
                    d._active_stream_loop_ids.discard(effective_loop_id)  # Bug 4.3

                # IG-054: Moved post-query logic here since we don't await task
                final_thread_id = d._runner.current_thread_id or ""
                if final_thread_id and final_thread_id != thread_id:
                    final_logger = ThreadLogger(
                        thread_id=final_thread_id,
                        retention_days=d._config.observability.thread_logging_retention_days,
                        max_size_mb=d._config.observability.thread_logging_max_size_mb,
                    )
                    final_logger.log_user_input(effective_text)
                    if full_response:
                        final_logger.log_assistant_response("".join(full_response))
                elif full_response:
                    thread_logger.log_assistant_response("".join(full_response))

                if final_thread_id:
                    await d._runner.touch_thread_activity_timestamp(final_thread_id)

                if effective_loop_id:
                    await d._broadcast(
                        self._loop_scoped_client_message(
                            effective_loop_id,
                            {"type": "status", "state": "idle"},
                        )
                    )

                if client_id:
                    await d._session_manager.release_loop_ownership(client_id)
                d._current_query_task = None

        try:
            task = asyncio.create_task(_run_stream())
            d._current_query_task = task
            d._active_threads[thread_id] = task
            # Yield once so _run_stream begins before run_query returns; otherwise /cancel
            # can run before the coroutine starts and skip finally cleanup.
            await asyncio.sleep(0)
            # IG-054: DO NOT await task - let it run in background
            # This allows the input loop to process concurrent queries
            # The task's internal finally block handles cleanup
        except asyncio.CancelledError:
            logger.info("Query task cancelled during creation")
            d._runner.set_current_thread_id(None)
            raise
        except Exception:
            logger.exception("Failed to create query task")
            d._query_running = False
            if thread_id in d._active_threads:
                d._active_threads.pop(thread_id, None)
            if client_id:
                await d._session_manager.release_loop_ownership(client_id)
            raise

    async def _await_cancel_after_signal(self, task: asyncio.Task, label: str) -> None:
        """Await task cancellation without forging daemon state (IG-398).

        Uses ``asyncio.shield`` so ``wait_for`` timeout does not cancel the query task;
        slow subagent unwind continues until ``_run_stream`` finally clears bookkeeping.

        Args:
            task: The asyncio task running ``_run_stream``.
            label: Thread id or ``current`` for logs.
        """
        d = self._daemon
        grace = float(getattr(d._daemon_config, "cancel_grace_seconds", 30))
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=grace)
        except TimeoutError:
            logger.warning(
                "Query task %s still unwinding after %.1fs; awaiting completion in background",
                label,
                grace,
            )
            asyncio.create_task(self._drain_cancelled_task(task, label))
        except asyncio.CancelledError:
            pass

    async def _drain_cancelled_task(self, task: asyncio.Task, label: str) -> None:
        """Await a cancelled query task until ``_run_stream`` finally completes."""
        try:
            await task
        except asyncio.CancelledError:
            logger.debug("Background cancel drain finished for %s", label)
        except Exception:
            logger.debug(
                "Background cancel drain for %s completed with exception",
                label,
                exc_info=True,
            )

    async def cancel_current_query(self) -> None:
        """Cancel the currently running query if any.

        Signals cancellation and awaits unwind up to ``daemon.cancel_grace_seconds``.
        Does not mutate ``_active_threads``, ``_current_query_task``, or broadcast
        ``idle`` — those are owned by ``_run_stream`` finally blocks (IG-398).
        """
        d = self._daemon
        tasks_to_cancel: list[tuple[str, asyncio.Task]] = []
        seen: set[int] = set()
        for tid, t in list(d._active_threads.items()):
            if t is not None and not t.done() and id(t) not in seen:
                tasks_to_cancel.append((str(tid), t))
                seen.add(id(t))
        ct = d._current_query_task
        if ct is not None and not ct.done() and id(ct) not in seen:
            tasks_to_cancel.append(("current", ct))

        if not tasks_to_cancel:
            return

        await d._broadcast(
            {
                "type": "command_response",
                "content": "[yellow]Cancellation requested.[/yellow]",
            }
        )

        for label, task in tasks_to_cancel:
            logger.info("Cancelling query task %s", label)
            task.cancel()
            await self._await_cancel_after_signal(task, label)

    async def cancel_loop(self, loop_id: str) -> None:
        """Cancel running query tasks bound to ``loop_id`` (IG-408).

        Signals the pool/local subprocess runner for ``loop_id`` *before* awaiting
        asyncio task unwind so ``cancel_request`` runs even if ``_run_stream`` finally
        would otherwise pop ``_active_runners`` first (subprocess would never see cancel).
        """
        lidq = str(loop_id or "").strip()
        if not lidq:
            logger.warning("cancel_loop called with empty loop_id; ignoring (no cancellation)")
            return

        d = self._daemon
        tasks_to_cancel: list[tuple[str, asyncio.Task]] = []
        seen: set[int] = set()
        for tid, t in list(d._active_threads.items()):
            if (
                d._thread_registry.get_thread_loop(tid) == lidq
                and t is not None
                and not t.done()
                and id(t) not in seen
            ):
                tasks_to_cancel.append((str(tid), t))
                seen.add(id(t))
        ct = d._current_query_task
        cur = d._runner.current_thread_id if d._runner else None
        if (
            ct is not None
            and not ct.done()
            and id(ct) not in seen
            and cur
            and d._thread_registry.get_thread_loop(cur) == lidq
        ):
            tasks_to_cancel.append(("current", ct))
            seen.add(id(ct))

        # RFC-221: signal the pool/local subprocess runner *before* awaiting asyncio
        # task unwind. Otherwise ``_run_stream`` finally pops the runner first and
        # ``cancel_request`` (cooperative cancel_event) never runs.
        loop_runner = self._active_runners.pop(lidq, None)
        if loop_runner is not None:
            try:
                await loop_runner.cancel()
            except Exception:
                logger.debug(
                    "cancel_loop: loop_runner.cancel failed loop_id=%s",
                    lidq[:16],
                    exc_info=True,
                )

        if not tasks_to_cancel:
            if loop_runner is None:
                return
            await d._broadcast(
                {
                    "type": "command_response",
                    "content": "[yellow]Cancellation requested.[/yellow]",
                    "loop_id": lidq,
                }
            )
            return

        await d._broadcast(
            {
                "type": "command_response",
                "content": "[yellow]Cancellation requested.[/yellow]",
                "loop_id": lidq,
            }
        )

        for label, task in tasks_to_cancel:
            logger.info("Cancelling query task %s for loop %s", label, lidq[:16])
            task.cancel()
            await self._await_cancel_after_signal(task, label)

    async def cancel_thread(self, checkpoint_thread_id: str) -> None:
        """Cancel a specific query task keyed by LangGraph checkpoint id."""
        d = self._daemon
        query_state_lock = getattr(d, "_query_state_lock", None)
        if query_state_lock:
            async with query_state_lock:
                await self._cancel_thread_locked(checkpoint_thread_id)
        else:
            await self._cancel_thread_locked(checkpoint_thread_id)

    async def _cancel_thread_locked(self, checkpoint_thread_id: str) -> None:
        d = self._daemon
        task = d._active_threads.get(checkpoint_thread_id)
        if task is not None and not task.done():
            logger.info("Cancelled query task for checkpoint %s", checkpoint_thread_id[:16])
            task.cancel()
            await self._await_cancel_after_signal(task, checkpoint_thread_id)
            return

        if d._current_query_task and not d._current_query_task.done():
            current_thread = d._runner.current_thread_id if d._runner else None
            if current_thread == checkpoint_thread_id:
                logger.info(
                    "Cancelled current query (legacy single-threaded, checkpoint=%s)",
                    checkpoint_thread_id[:16],
                )
                d._current_query_task.cancel()
                await self._await_cancel_after_signal(d._current_query_task, checkpoint_thread_id)
                return

        logger.debug("Checkpoint %s not found or already complete", checkpoint_thread_id[:16])
        if d._runner and d._runner.current_thread_id == checkpoint_thread_id:
            d._runner.set_current_thread_id(None)

    async def ensure_active_checkpoint_thread_id(self, client_id: str | None = None) -> str:
        """Ensure the runner has a concrete LangGraph checkpoint id.

        Prefer the checkpoint last bound to ``client_id`` (legacy thread_create /
        new_thread / resume) so ad-hoc paths do not mint a duplicate persisted
        checkpoint when the runner has no global current id (IG-361).
        """
        d = self._daemon
        if client_id:
            mapped = (d._thread_registry.get_client_thread(client_id) or "").strip()
            if mapped:
                d._runner.set_current_thread_id(mapped)
                return mapped

        current = str(d._runner.current_thread_id or "").strip()
        if current:
            return current

        thread_info = await d._runner.create_persisted_thread()
        tid = thread_info.thread_id
        d._runner.set_current_thread_id(tid)
        d._thread_registry.ensure(tid, is_draft=False)
        d._thread_registry.set_workspace(tid, Path(d._daemon_workspace))
        return tid

    async def _bridge_subprocess_interrupt(
        self,
        d: Any,
        marker: Any,
        loop_runner: Any,
        thread_id: str,
        client_id: str | None,
        loop_id: str | None,
    ) -> None:
        """Bridge an HITL interrupt from a subprocess worker to the client.

        Creates an ``asyncio.Future`` for the interrupt. When the client sends
        ``resume_interrupts``, the future resolves and the payload is forwarded
        to the subprocess worker through ``loop_runner.forward_interrupt_resume``.

        Args:
            d: The daemon instance.
            marker: The ``InterruptPending`` marker yielded by the runner.
            loop_runner: The loop runner that can forward the resume payload.
            thread_id: Checkpoint thread identifier.
            client_id: Connected client identifier.
            loop_id: Active loop identifier.
        """
        from soothe.core.loop.engine.hitl_scope import timeout_default_hitl_resume_payload

        if not loop_id:
            from soothe.core.loop.engine.hitl_scope import auto_approve_interrupt_resume_payload

            payload = auto_approve_interrupt_resume_payload(marker.pending_interrupts)
            await loop_runner.forward_interrupt_resume(marker.loop_id, payload)
            return

        event_loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = event_loop.create_future()
        d._pending_interrupt_responses[loop_id] = future
        timeout_s = int(getattr(d._daemon_config, "hitl_timeout_seconds", 0) or 0)

        logger.debug(
            "Subprocess interrupt pending (loop=%s checkpoint=%s client=%s hitl_timeout=%s)",
            loop_id[:16],
            thread_id[:16] if thread_id else "?",
            client_id,
            timeout_s if timeout_s > 0 else "unlimited",
        )

        try:
            if timeout_s > 0:
                try:
                    resume_payload = await asyncio.wait_for(future, timeout=float(timeout_s))
                except TimeoutError:
                    logger.warning(
                        "HITL timed out after %ds (loop=%s); resuming with default-first choices",
                        timeout_s,
                        loop_id[:16],
                    )
                    if not future.done():
                        future.cancel()
                    resume_payload = timeout_default_hitl_resume_payload(marker.pending_interrupts)
            else:
                resume_payload = await future
        finally:
            d._pending_interrupt_responses.pop(loop_id, None)

        await loop_runner.forward_interrupt_resume(marker.loop_id, resume_payload)
