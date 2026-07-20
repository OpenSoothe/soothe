"""Query execution lifecycle for the daemon (IG-110).

Owns streaming, cancellation, and per-thread logging hooks. Uses
``SootheRunner`` public APIs only (no direct ``_durability`` access from
handlers).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from soothe.foundation.events import ERROR
from soothe.logging import ThreadLogger, set_thread_id
from soothe_sdk.display.text_extract import extract_text_from_ai_message
from soothe_sdk.ux.stream_tool_wire import (
    TOOL_CALL_UPDATES_BATCH,
    extract_tool_call_updates_from_wire_message,
)
from soothe_sdk.wire.codec import prepare_stream_data_for_wire
from soothe_sdk.wire.protocol import _serialize_for_json

from soothe_daemon.bootstrap.logging import set_client_id, set_loop_id
from soothe_daemon.protocol.intent_hints import is_daemon_intent_hint
from soothe_daemon.query.stream_delivery import StreamDeliveryCoalescer
from soothe_daemon.services.image_understanding import enrich_user_text_with_vision
from soothe_daemon.services.intent_hint_turn import run_intent_hint_turn
from soothe_daemon.utils.error_events import emit_error_event

logger = logging.getLogger(__name__)

_STREAM_CHUNK_LENGTH = 3
_MSG_PAIR_LENGTH = 2
# IG-477: cap in-query assistant text accumulation (~100KB)
_MAX_FULL_RESPONSE_CHARS = 100_000


async def _peek_goal_completion_from_ledger(card_manager: Any, loop_id: str) -> str:
    """Return the best assistant completion body from the live display ledger."""
    from soothe_sdk.display.transcript_types import MessageType

    ledger = await card_manager.ensure_for_loop(loop_id)
    cards = ledger.snapshot()
    for card in reversed(cards):
        if card.type != MessageType.ASSISTANT:
            continue
        if card.loop_output_phase == "goal_completion":
            content = (card.content or "").strip()
            if content:
                return content
    for card in reversed(cards):
        if card.type == MessageType.ASSISTANT:
            content = (card.content or "").strip()
            if content:
                return content
    return ""


class QueryAdmission(StrEnum):
    """Result of daemon query admission under ``_query_state_lock``."""

    ADMITTED = "admitted"
    DAEMON_BUSY = "daemon_busy"
    LOOP_BUSY = "loop_busy"


@dataclass(frozen=True, slots=True)
class _ActiveLoopRunner:
    """Runner handle scoped to a single admitted loop turn."""

    runner: Any
    turn_generation: int


class AsyncCancelOrchestrator:
    """Manages async cancellation with retry and force kill - guarantees success.

    When cancel_loop() is called, this orchestrator kicks off a background task
    that:
    1. Signals cooperative cancellation (cancel_event)
    2. Retries with exponential backoff up to cancel_retry_count
    3. Force kills the worker if retries are exhausted

    The caller returns immediately; cancellation is guaranteed in background.
    """

    def __init__(self, daemon: Any, query_engine: QueryEngine) -> None:
        """Initialize orchestrator with daemon and query engine references."""
        self._daemon = daemon
        self._query_engine = query_engine
        self._active_cancel_tasks: dict[str, asyncio.Task] = {}

    async def start_async_cancel(self, loop_id: str, already_signaled: bool = False) -> None:
        """Kick off async cancel, return immediately. Cancel guaranteed in background.

        Deduplicates cancel requests: only one background task per loop_id.

        Args:
            loop_id: The loop to cancel.
            already_signaled: If True, runner.cancel() was already called by caller.
        """
        # Deduplicate: only one cancel task per loop
        if loop_id in self._active_cancel_tasks:
            existing = self._active_cancel_tasks[loop_id]
            if not existing.done():
                logger.debug("Already cancelling loop %s, skipping duplicate", loop_id[:16])
                return

        # Spawn background task that guarantees cancel
        task = asyncio.create_task(
            self._cancel_with_retry_and_force(loop_id, already_signaled=already_signaled),
            name=f"cancel-{loop_id[:8]}",
        )
        self._active_cancel_tasks[loop_id] = task
        task.add_done_callback(lambda _: self._active_cancel_tasks.pop(loop_id, None))

    async def _cancel_with_retry_and_force(
        self, loop_id: str, already_signaled: bool = False
    ) -> None:
        """Execute cancellation with retry loop and force kill fallback.

        Always succeeds: either cooperative cancel works, or force kill terminates.

        Args:
            loop_id: The loop to cancel.
            already_signaled: If True, runner.cancel() was already called by caller.
        """
        config = self._daemon._daemon_config
        max_retries = getattr(config, "cancel_retry_count", 3)
        base_interval = getattr(config, "cancel_retry_interval_seconds", 2.0)
        force_timeout = getattr(config, "cancel_force_kill_timeout_seconds", 10.0)

        runner_entry = self._query_engine._active_runners.get(loop_id)
        runner = runner_entry.runner if runner_entry is not None else None
        worker_id = await self._get_worker_id_for_loop(loop_id)

        # Collect asyncio tasks to cancel
        tasks_to_cancel = self._collect_tasks_for_loop(loop_id)

        # Cancel asyncio tasks immediately
        for label, task in tasks_to_cancel:
            if not task.done():
                task.cancel()

        # Retry loop for cooperative cancellation
        for attempt in range(max_retries):
            try:
                # Signal cooperative cancel to worker pool (unless already done by caller)
                if runner is not None and not already_signaled:
                    try:
                        await runner.cancel()
                    except Exception:
                        logger.debug(
                            "Cancel attempt %d: runner.cancel failed for loop %s",
                            attempt + 1,
                            loop_id[:16],
                            exc_info=True,
                        )

                # Wait for cooperative response (exponential backoff)
                wait_time = base_interval * (0.5 + attempt * 0.5)
                await asyncio.sleep(wait_time)

                # Check if worker is now idle (cancel succeeded)
                if await self._is_worker_idle(worker_id):
                    logger.info(
                        "Cancel succeeded for loop %s (attempt %d)",
                        loop_id[:16],
                        attempt + 1,
                    )
                    # Await cancelled tasks briefly to let them unwind
                    for label, task in tasks_to_cancel:
                        if not task.done():
                            try:
                                await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
                            except (TimeoutError, asyncio.CancelledError):
                                pass
                    self._query_engine._clear_loop_cancel_armed_state(loop_id)
                    return  # Success

                # Update tasks list (some may have completed)
                tasks_to_cancel = self._collect_tasks_for_loop(loop_id)

            except Exception as e:
                logger.warning(
                    "Cancel attempt %d for loop %s failed: %s",
                    attempt + 1,
                    loop_id[:16],
                    e,
                )

        # Retries exhausted - force kill guarantees success
        logger.warning(
            "Cooperative cancel failed for loop %s after %d attempts, force killing",
            loop_id[:16],
            max_retries,
        )
        await self._force_kill_worker(worker_id, loop_id, timeout=force_timeout)

        # Cleanup bookkeeping (runner unregister is turn-scoped in stream finally).
        self._query_engine._clear_loop_cancel_armed_state(loop_id)
        await self._query_engine._release_query_admission(loop_id)

    async def _get_execution_pool(self) -> Any | None:
        """Return the shared thread/process execution pool."""
        factory = getattr(self._daemon, "_runner_factory", None)
        if factory is None or not hasattr(factory, "get_shared_execution_pool"):
            return None
        return await factory.get_shared_execution_pool()

    async def _get_worker_id_for_loop(self, loop_id: str) -> str | None:
        """Get worker_id handling the given loop_id from the execution pool."""
        pool = await self._get_execution_pool()
        if pool is not None and hasattr(pool, "get_worker_id_for_loop"):
            return pool.get_worker_id_for_loop(loop_id)
        return None

    async def _is_worker_idle(self, worker_id: str | None) -> bool:
        """Check if worker has returned to idle state."""
        if worker_id is None:
            return False
        pool = await self._get_execution_pool()
        if pool is not None and hasattr(pool, "is_worker_idle"):
            return pool.is_worker_idle(worker_id)
        return False

    async def _force_kill_worker(self, worker_id: str | None, loop_id: str, timeout: float) -> None:
        """Force terminate worker - guarantees cancel succeeds."""
        if worker_id is None:
            logger.warning("No worker_id for loop %s, cannot force kill", loop_id[:16])
            return

        pool = await self._get_execution_pool()
        if pool is None:
            return

        runner_type = self._daemon._daemon_config.validate_runner_mode()

        if runner_type == "worker_pool" and hasattr(pool, "force_kill_worker"):
            await pool.force_kill_worker(worker_id, timeout)
        elif runner_type == "thread_pool" and hasattr(pool, "force_cancel_worker"):
            await pool.force_cancel_worker(worker_id, timeout)
        else:
            logger.warning(
                "Runner type %s does not support force kill for worker %s",
                runner_type,
                worker_id,
            )

    def _collect_tasks_for_loop(self, loop_id: str) -> list[tuple[str, asyncio.Task]]:
        """Collect asyncio tasks associated with the given loop_id."""
        return self._query_engine.collect_active_tasks_for_loop(loop_id)


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
        # RFC-221: per-loop runner instances keyed by loop_id (turn-scoped).
        self._active_runners: dict[str, _ActiveLoopRunner] = {}
        # Monotonic turn counter per loop; stale finally blocks must not emit
        # terminal frames or cancel a successor runner.
        self._loop_turn_generation: dict[str, int] = {}
        # IG-659: monotonic outbound seq per loop for client stale-drop.
        self._loop_event_seq: dict[str, int] = {}
        # IG-659 phase 4: loops still emitting prior-turn terminals after
        # admission release — next admit must wait.
        self._loops_finalizing: set[str] = set()
        # Optional override while a turn broadcasts (emitting generation).
        self._broadcast_turn_generation: dict[str, int] = {}
        # Async cancel orchestrator for guaranteed cancellation
        self._cancel_orchestrator: AsyncCancelOrchestrator | None = None
        # Loop ids cancelled before their query task was registered. The early
        # ``running`` broadcast (server/handlers.py) can let a ``/cancel`` arrive
        # before ``run_query`` creates the asyncio task; without this set the
        # cancel would be lost. ``_run_stream`` checks membership at start and
        # aborts immediately, emitting ``idle`` so the client observes the
        # cancellation.
        self._pending_cancels: set[str] = set()
        # Loop ids with an early ``running`` broadcast before ``run_query`` admits.
        self._loops_turn_starting: set[str] = set()

    def mark_loop_turn_starting(self, loop_id: str) -> None:
        """Record that a loop turn is starting (pre-``run_query`` race window).

        Called when the loop worker emits early ``running`` so a concurrent
        ``/cancel`` can arm ``_pending_cancels`` without treating idle cancels as
        pre-start aborts.
        """
        lid = str(loop_id or "").strip()
        if lid:
            self._loops_turn_starting.add(lid)

    def is_cancel_in_progress(self, loop_id: str) -> bool:
        """Return whether a background cancel task is still running for ``loop_id``."""
        orchestrator = self._cancel_orchestrator
        if orchestrator is None:
            return False
        task = orchestrator._active_cancel_tasks.get(loop_id)
        return task is not None and not task.done()

    def _owns_turn(self, loop_id: str | None, turn_generation: int) -> bool:
        """Return whether ``turn_generation`` is still the active turn for ``loop_id``."""
        if not loop_id:
            return True
        return self._loop_turn_generation.get(loop_id) == turn_generation

    async def _get_execution_pool(self) -> Any | None:
        """Return the shared thread/process execution pool when configured."""
        factory = getattr(self._daemon, "_runner_factory", None)
        if factory is None or not hasattr(factory, "get_shared_execution_pool"):
            return None
        return await factory.get_shared_execution_pool()

    async def await_loop_ready_for_turn(self, loop_id: str) -> None:
        """Wait for cancel orchestration and worker teardown before a new turn.

        Queued ``loop_input`` after Ctrl+C must not race the prior turn's
        asyncio finally block or an in-flight pool worker.
        """
        lid = str(loop_id or "").strip()
        if not lid:
            return

        orchestrator = self._cancel_orchestrator
        if orchestrator is not None:
            task = orchestrator._active_cancel_tasks.get(lid)
            if task is not None and not task.done():
                try:
                    await task
                except Exception:
                    logger.debug(
                        "await_loop_ready_for_turn: cancel task failed loop=%s",
                        lid[:16],
                        exc_info=True,
                    )

        pool = await self._get_execution_pool()
        if pool is not None and hasattr(pool, "await_loop_dispatchable"):
            await pool.await_loop_dispatchable(lid)

        # Direct intent-hint turns do not occupy execution pool workers, but they
        # still hold per-loop query admission until stream-finally completes.
        # Queue workers can invoke run_query again before that finally runs; wait
        # here so the follow-up turn is deferred instead of being rejected LOOP_BUSY.
        # IG-659 phase 4: also wait while prior turn is still emitting terminals.
        while True:
            async with self._daemon._query_state_lock:
                if (
                    lid not in self._daemon._loops_with_active_query
                    and lid not in self._loops_finalizing
                ):
                    break
            await asyncio.sleep(0.01)

    def _should_arm_pending_cancel(self, loop_id: str) -> bool:
        """Return True only for the genuine pre-registration cancel race window."""
        if self.collect_active_tasks_for_loop(loop_id):
            return False
        if loop_id in self._active_runners:
            return False
        if self.is_cancel_in_progress(loop_id):
            return False
        d = self._daemon
        if loop_id in d._loops_with_active_query:
            return True
        return loop_id in self._loops_turn_starting

    def _clear_loop_cancel_armed_state(self, loop_id: str) -> None:
        """Drop pre-start cancel bookkeeping once cancel completes or turn ends."""
        self._pending_cancels.discard(loop_id)
        self._loops_turn_starting.discard(loop_id)

    def collect_active_tasks_for_loop(self, loop_id: str) -> list[tuple[str, asyncio.Task]]:
        """Return in-flight query asyncio tasks bound to ``loop_id``."""
        d = self._daemon
        tasks: list[tuple[str, asyncio.Task]] = []
        seen: set[int] = set()

        for tid, t in list(d._active_threads.items()):
            if (
                d._thread_registry.get_thread_loop(tid) == loop_id
                and t is not None
                and not t.done()
                and id(t) not in seen
            ):
                tasks.append((str(tid), t))
                seen.add(id(t))

        ct = d._current_query_task
        cur = d._runner.current_thread_id if d._runner else None
        if (
            ct is not None
            and not ct.done()
            and id(ct) not in seen
            and cur
            and d._thread_registry.get_thread_loop(cur) == loop_id
        ):
            tasks.append(("current", ct))
            seen.add(id(ct))

        return tasks

    def _next_loop_seq(self, loop_id: str) -> int:
        """Allocate the next monotonic outbound seq for ``loop_id``."""
        lid = str(loop_id or "").strip()
        nxt = self._loop_event_seq.get(lid, 0) + 1
        self._loop_event_seq[lid] = nxt
        return nxt

    def _resolve_broadcast_generation(
        self, loop_id: str, turn_generation: int | None = None
    ) -> int:
        """Return generation to stamp on outbound frames for ``loop_id``.

        Pass ``turn_generation=0`` to omit ``turn_id`` (pre-admit early
        ``running`` must not reuse the prior turn's generation).
        """
        if turn_generation is not None:
            return max(0, int(turn_generation))
        ctx = self._broadcast_turn_generation.get(loop_id)
        if ctx is not None and ctx > 0:
            return ctx
        return int(self._loop_turn_generation.get(loop_id, 0) or 0)

    def _loop_scoped_client_message(
        self,
        loop_id: str,
        payload: dict[str, Any],
        *,
        turn_generation: int | None = None,
    ) -> dict[str, Any]:
        """Build a client-visible frame: ``loop_id``, ``turn_id``, ``seq`` (IG-659)."""
        from soothe_daemon.query.turn_boundary import format_turn_id

        out = dict(payload)
        out["loop_id"] = str(loop_id).strip()
        out.pop("thread_id", None)
        gen = self._resolve_broadcast_generation(loop_id, turn_generation)
        turn_id = format_turn_id(loop_id, gen) if gen > 0 else ""
        if turn_id and "turn_id" not in out:
            out["turn_id"] = turn_id
        if "seq" not in out:
            out["seq"] = self._next_loop_seq(loop_id)
        # Mirror turn_id into custom terminal payloads for nested readers.
        if turn_id and out.get("type") == "event" and out.get("mode") == "custom":
            data = out.get("data")
            if isinstance(data, dict) and "turn_id" not in data:
                data = dict(data)
                data["turn_id"] = turn_id
                out["data"] = data
        return out

    async def _broadcast_loop_message(
        self,
        loop_id: str,
        payload: dict[str, Any],
        *,
        turn_generation: int | None = None,
    ) -> None:
        """Broadcast one loop-scoped frame with per-loop in-flight budget (IG-534 2.2)."""
        d = self._daemon
        scoped = self._loop_scoped_client_message(loop_id, payload, turn_generation=turn_generation)
        budget = getattr(d, "_loop_broadcast_budget", None)
        if budget is not None:
            async with budget.slot(loop_id):
                await d._broadcast(scoped)
            return
        await d._broadcast(scoped)

    async def _emit_turn_stream_end(
        self,
        loop_id: str,
        *,
        reason: str | None = None,
        turn_generation: int | None = None,
    ) -> None:
        """Broadcast ``soothe.stream.end`` with ``scope=turn`` (IG-556 / IG-659)."""
        from soothe_sdk.core.events import STREAM_END

        from soothe_daemon.query.turn_boundary import format_turn_id

        data: dict[str, Any] = {"type": STREAM_END, "scope": "turn"}
        if reason:
            data["reason"] = reason
        gen = self._resolve_broadcast_generation(loop_id, turn_generation)
        turn_id = format_turn_id(loop_id, gen) if gen > 0 else ""
        if turn_id:
            data["turn_id"] = turn_id
        await self._broadcast_loop_message(
            loop_id,
            {
                "type": "event",
                "namespace": [],
                "mode": "custom",
                "data": data,
            },
            turn_generation=turn_generation,
        )

    async def _admit_query(
        self,
        *,
        effective_loop_id: str | None,
        thread_id: str,
    ) -> tuple[QueryAdmission, int]:
        """Reserve daemon / per-loop query capacity atomically.

        Returns:
            Tuple of admission result and turn generation (0 when not loop-scoped).
        """
        d = self._daemon
        max_concurrent = getattr(d._daemon_config, "max_concurrent_threads", 100)
        async with d._query_state_lock:
            if max_concurrent > 0 and len(d._active_threads) >= max_concurrent:
                return QueryAdmission.DAEMON_BUSY, 0
            if effective_loop_id and effective_loop_id in d._loops_with_active_query:
                return QueryAdmission.LOOP_BUSY, 0
            if effective_loop_id and effective_loop_id in self._loops_finalizing:
                return QueryAdmission.LOOP_BUSY, 0
            turn_generation = 0
            if effective_loop_id:
                turn_generation = self._loop_turn_generation.get(effective_loop_id, 0) + 1
                self._loop_turn_generation[effective_loop_id] = turn_generation
                d._loops_with_active_query.add(effective_loop_id)
            return QueryAdmission.ADMITTED, turn_generation

    async def _release_query_admission(self, effective_loop_id: str | None) -> None:
        """Drop per-loop admission reservation when a query ends or aborts early."""
        if not effective_loop_id:
            return
        d = self._daemon
        async with d._query_state_lock:
            d._loops_with_active_query.discard(effective_loop_id)
        self._loops_turn_starting.discard(effective_loop_id)

    async def _register_query_task(self, thread_id: str, task: asyncio.Task[Any]) -> None:
        """Register a background query task under ``_query_state_lock``."""
        d = self._daemon
        async with d._query_state_lock:
            d._active_threads[thread_id] = task
            d._current_query_task = task

    async def _unregister_query_task(
        self, thread_id: str, task: asyncio.Task[Any] | None = None
    ) -> None:
        """Remove a query task registration under ``_query_state_lock``.

        When ``task`` is provided the entry is only dropped if it still matches,
        so a superseded turn cannot evict a successor that reused the same
        checkpoint ``thread_id``.
        """
        d = self._daemon
        async with d._query_state_lock:
            if task is not None and d._active_threads.get(thread_id) is not task:
                return
            d._active_threads.pop(thread_id, None)

    async def _reject_query_admission(
        self,
        admission: QueryAdmission,
        *,
        effective_loop_id: str | None,
        client_id: str | None,
    ) -> None:
        """Broadcast rejection and release ownership when admission fails."""
        d = self._daemon
        max_concurrent = getattr(d._daemon_config, "max_concurrent_threads", 100)
        if admission == QueryAdmission.DAEMON_BUSY:
            error = (
                f"Daemon has reached its concurrent query limit ({max_concurrent}). "
                "Wait for a query to finish or cancel one before starting a new one."
            )
            code = "DAEMON_BUSY"
        else:
            error = (
                "This loop already has a query in progress. "
                "Wait for it to finish or cancel before starting another."
            )
            code = "LOOP_BUSY"

        if effective_loop_id:
            await self._broadcast_loop_message(
                effective_loop_id,
                {
                    "type": "event",
                    "namespace": [],
                    "mode": "custom",
                    "data": {"type": ERROR, "error": error, "code": code},
                },
            )
            await self._broadcast_loop_message(
                effective_loop_id,
                {"type": "status", "state": "idle"},
            )
        if client_id:
            await d._session_manager.release_loop_ownership(client_id)

    def _prepare_stream_tuple_events(
        self,
        namespace: tuple[str, ...],
        mode: str,
        data: Any,
        *,
        coalescer: Any | None = None,
    ) -> tuple[list[dict[str, Any]], Any | None]:
        """Expand one runner tuple into wire events and optional card-ingest payload."""
        if mode == "updates":
            return [], None

        wire_data = prepare_stream_data_for_wire(data) if mode == "messages" else data
        events: list[dict[str, Any]] = []
        stripped_tool_metadata = False
        if (
            mode == "messages"
            and isinstance(wire_data, (tuple, list))
            and len(wire_data) == _MSG_PAIR_LENGTH
        ):
            msg_wire = wire_data[0] if wire_data else None
            if isinstance(msg_wire, dict):
                tool_updates = list(extract_tool_call_updates_from_wire_message(msg_wire))
                if tool_updates:
                    events.append(
                        {
                            "type": "event",
                            "namespace": list(namespace),
                            "mode": "custom",
                            "data": {
                                "type": TOOL_CALL_UPDATES_BATCH,
                                "updates": tool_updates,
                                "count": len(tool_updates),
                            },
                        }
                    )
                    if coalescer is not None:
                        wire_data = coalescer.strip_tool_metadata_for_batch(wire_data)
                        stripped_tool_metadata = True
        if stripped_tool_metadata:
            body = wire_data[0] if wire_data else None
            if isinstance(body, dict):
                from soothe_sdk.wire.codec import flatten_enveloped_message_dict

                flat = flatten_enveloped_message_dict(body)
                text = "".join(extract_text_from_ai_message(flat)).strip()
                has_content = bool(text)
                has_phase = bool(flat.get("phase"))
                if not has_content and not has_phase:
                    return events, wire_data
        if (
            mode == "messages"
            and isinstance(wire_data, (tuple, list))
            and len(wire_data) == _MSG_PAIR_LENGTH
            and coalescer is not None
            and coalescer.should_skip_tool_message_wire(wire_data[0])
        ):
            return events, None
        events.append(
            {
                "type": "event",
                "namespace": list(namespace),
                "mode": mode,
                "data": wire_data,
            }
        )
        return events, wire_data

    async def _broadcast_coalescer_outputs(
        self,
        loop_id: str,
        outputs: list[tuple[tuple[str, ...], str, Any]],
        *,
        coalescer: Any | None = None,
    ) -> None:
        """Broadcast all tuples from one coalescer step as a single batch when possible."""
        if not outputs:
            return

        batch_events: list[dict[str, Any]] = []
        d = self._daemon
        card_manager = getattr(d, "_card_manager", None)

        for namespace, mode, data in outputs:
            events, wire_data = self._prepare_stream_tuple_events(
                namespace,
                mode,
                data,
                coalescer=coalescer,
            )
            batch_events.extend(events)
            if card_manager is not None and wire_data is not None:
                try:
                    await card_manager.ingest_stream_tuple(loop_id, namespace, mode, wire_data)
                except Exception:
                    logger.debug(
                        "Card stream binding enqueue failed for loop %s", loop_id, exc_info=True
                    )

        if not batch_events:
            return

        if len(batch_events) == 1:
            await self._broadcast_loop_message(loop_id, batch_events[0])
            return

        scoped = [self._loop_scoped_client_message(loop_id, event) for event in batch_events]
        await self._broadcast_loop_message(
            loop_id,
            {"type": "event_batch", "events": scoped},
        )

    async def _broadcast_stream_tuple(
        self,
        loop_id: str,
        namespace: tuple[str, ...],
        mode: str,
        data: Any,
        *,
        coalescer: Any | None = None,
    ) -> None:
        """Broadcast one runner stream tuple to loop subscribers."""
        await self._broadcast_coalescer_outputs(
            loop_id,
            [(namespace, mode, data)],
            coalescer=coalescer,
        )

    def _get_output_streaming_config(self, daemon: Any) -> dict[str, Any]:
        """Get output streaming config parameters from daemon config (RFC-614)."""
        config = getattr(daemon, "_config", None)
        if config is None:
            return {
                "adaptive_threshold_chars": 1000,
                "file_output_threshold_chars": 0,
                "file_output_preview_chars": 500,
                "file_output_dir": None,
            }
        streaming_cfg = config.agent.loop.output_streaming
        return {
            "adaptive_threshold_chars": streaming_cfg.adaptive_threshold_chars,
            "file_output_threshold_chars": streaming_cfg.file_output_threshold_chars,
            "file_output_preview_chars": streaming_cfg.file_output_preview_chars,
            "file_output_dir": streaming_cfg.file_output_dir,
            "streaming_interval_ms": streaming_cfg.streaming_interval_ms,
            "message_coalesce_enabled": streaming_cfg.message_coalesce_enabled,
            "tool_batch_enabled": streaming_cfg.tool_batch_enabled,
            "tool_batch_interval_ms": streaming_cfg.tool_batch_interval_ms,
            "suppress_redundant_stream_tool_updates": (
                streaming_cfg.suppress_redundant_stream_tool_updates
            ),
            "skip_redundant_tool_message_wire": streaming_cfg.skip_redundant_tool_message_wire,
        }

    async def _mark_active_context_goals_cancelled(
        self,
        loop_id: str,
        *,
        reason: str = "user_cancelled",
    ) -> int:
        """Mark active ContextEngine goals cancelled and persist the DAG.

        The `/context` popup reads persisted CE DAG state. When a turn is
        interrupted mid-flight, we need to transition active goals to
        ``cancelled`` before stream teardown so cancelled attempts remain visible
        in the DAG view.
        """
        lid = str(loop_id or "").strip()
        if not lid:
            return 0

        try:
            from soothe.foundation.context.persistence.factory import (
                resolve_context_engine_persistence,
            )

            persistence = resolve_context_engine_persistence(self._daemon._config, lid)
            try:
                dag = await persistence.load_dag()
                if dag is None:
                    return 0

                now = datetime.now(UTC)
                cancelled = 0
                for goal in dag.goals.values():
                    if str(getattr(goal, "status", "")).strip().lower() != "active":
                        continue
                    goal.status = "cancelled"
                    if getattr(goal, "error", None) in (None, ""):
                        goal.error = reason
                    goal.updated_at = now
                    cancelled += 1

                if cancelled:
                    await persistence.save_dag(dag)
                    logger.info(
                        "Marked %d active CE goal(s) cancelled for loop %s",
                        cancelled,
                        lid[:16],
                    )
                    # RFC-214: also write a `goal_interrupted` ledger marker so the
                    # next goal's planning projection can bound this cancelled
                    # goal's partial segment and surface what was done. Best-effort;
                    # failures are swallowed inside the helper.
                    from soothe_daemon.query.goal_interrupt_persistence import (
                        mark_cancelled_goal_interrupted,
                    )

                    await mark_cancelled_goal_interrupted(self._daemon._config, lid, reason=reason)
                return cancelled
            finally:
                close = getattr(persistence, "close", None)
                if callable(close):
                    maybe_coro = close()
                    if asyncio.iscoroutine(maybe_coro):
                        await maybe_coro
        except Exception:
            logger.warning(
                "Failed to persist cancelled CE goals for loop %s",
                lid[:16],
                exc_info=True,
            )
            return 0

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
            thread_id = await self.ensure_active_checkpoint_thread_id()
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
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        router_profile: str | None = None,
        attachments: list[dict[str, str]] | None = None,
        checkpoint_thread_id: str | None = None,
        intent_hint: str | None = None,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str | None = None,
        response_schema_strict: bool | None = None,
        clarification_mode: str | None = None,
        clarification_answer: bool = False,
        clarification_answers: list[str] | None = None,
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
        if effective_loop_id:
            set_thread_id(effective_loop_id)
            set_loop_id(effective_loop_id)
        if client_id:
            set_client_id(client_id)

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

        # IG-054: Admit before vision preflight (IG-327) to avoid wasted image API calls.
        profile_name = (
            router_profile.strip()
            if isinstance(router_profile, str) and router_profile.strip()
            else None
        )
        if profile_name is not None:
            known = {p.name for p in (d._config.router_profiles or [])}
            if profile_name not in known:
                msg = f"Unknown router profile: {profile_name!r}"
                logger.warning("[Query] %s", msg)
                if client_id:
                    await d._send_client_message(
                        client_id,
                        {
                            "type": "error",
                            "code": "UNKNOWN_ROUTER_PROFILE",
                            "message": msg,
                        },
                    )
                if effective_loop_id:
                    await self._broadcast_loop_message(
                        effective_loop_id,
                        {"type": "status", "state": "idle"},
                    )
                return

        await self.await_loop_ready_for_turn(effective_loop_id or "")
        admission, turn_generation = await self._admit_query(
            effective_loop_id=effective_loop_id,
            thread_id=thread_id,
        )
        if admission is not QueryAdmission.ADMITTED:
            logger.warning(
                "Query admission rejected (%s) loop=%s checkpoint=%s",
                admission,
                effective_loop_id or "?",
                thread_id[:16] if thread_id else "?",
            )
            await self._reject_query_admission(
                admission,
                effective_loop_id=effective_loop_id,
                client_id=client_id,
            )
            return

        if is_daemon_intent_hint(intent_hint):
            await self._start_intent_hint_background(
                text=text,
                thread_id=thread_id,
                effective_loop_id=effective_loop_id,
                client_id=client_id,
                intent_hint_value=intent_hint,
                model=model,
                model_params=model_params,
                attachments=attachments,
                thread_logger=thread_logger,
                response_schema=response_schema,
                response_schema_name=response_schema_name,
                response_schema_strict=response_schema_strict,
                turn_generation=turn_generation,
            )
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
                    await self._broadcast_loop_message(
                        effective_loop_id,
                        {
                            "type": "event",
                            "namespace": [],
                            "mode": "custom",
                            "data": emit_error_event(exc),
                        },
                    )
                    await self._broadcast_loop_message(
                        effective_loop_id,
                        {"type": "status", "state": "idle"},
                    )
                await self._release_query_admission(effective_loop_id)
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

        if client_id and effective_loop_id:
            await d._session_manager.claim_loop_ownership(client_id, effective_loop_id)
            subscribed = await d._session_manager.subscribe_loop(client_id, effective_loop_id)
            if not subscribed:
                logger.warning(
                    "Client %s not found for loop %s subscription - query will run without client notifications",
                    client_id[:8],
                    effective_loop_id[:8],
                )

        # Note: the ``running`` status is broadcast *after* the query task is
        # registered below, so a concurrent ``/cancel`` arriving right after
        # ``running`` can still resolve the task via ``_active_threads`` /
        # ``_current_query_task`` and interrupt the stream. Broadcasting here
        # (before the task exists) opened a race where cancel was a no-op.

        full_response: list[str] = []
        full_response_chars: int = 0  # Track total characters for bounded accumulation
        goal_completion_response: list[str] = []
        goal_completion_chars: int = 0
        # Set to True once a phase-tagged loop assistant chunk (plan_direct,
        # goal_completion, autonomous_goal, intent-hint phases, chitchat) has been
        # persisted by ThreadLogger._log_message_event. When true, the legacy
        # ``log_assistant_response("".join(full_response))`` row at end-of-
        # stream is suppressed — the per-phase rows already cover the user-
        # visible answer, and the legacy concat row mixes plan_direct text
        # with raw tool outputs into a single malformed assistant card.
        phase_tagged_assistant_written = [False]
        turn_stream_end_emitted = False
        turn_cancelled = False

        async def _run_stream() -> None:
            nonlocal turn_stream_end_emitted, turn_cancelled

            if effective_loop_id:
                d._active_stream_loop_ids.add(effective_loop_id)  # Bug 4.3: set-based tracking
                self._broadcast_turn_generation[effective_loop_id] = turn_generation
            # Stream model / router-profile overlays are attached inside the loop
            # worker from ``LoopRunRequest`` (``stream_turn_overrides``). Parent
            # process ContextVars do not cross pool/thread/ray workers.

            async def _ensure_turn_stream_end() -> None:
                nonlocal turn_stream_end_emitted
                if turn_stream_end_emitted or not effective_loop_id:
                    return
                await self._emit_turn_stream_end(
                    effective_loop_id,
                    reason="cancelled" if turn_cancelled else None,
                    turn_generation=turn_generation,
                )
                turn_stream_end_emitted = True

            # Observe a pending cancel that arrived during the early-``running``
            # race window (before this task was registered). Abort immediately
            # so the client observes ``idle`` instead of a full stream run.
            if effective_loop_id and effective_loop_id in self._pending_cancels:
                logger.info(
                    "Query for loop %s cancelled before stream start",
                    effective_loop_id[:16],
                )
                if effective_loop_id:
                    d._active_stream_loop_ids.discard(effective_loop_id)
                    self._loops_finalizing.add(effective_loop_id)
                    try:
                        await self._emit_turn_stream_end(
                            effective_loop_id,
                            reason="cancelled",
                            turn_generation=turn_generation,
                        )
                        # Long-lived loop_events stays open; turn end is stream.end + idle.
                        await self._broadcast_loop_message(
                            effective_loop_id,
                            {"type": "status", "state": "idle"},
                            turn_generation=turn_generation,
                        )
                    finally:
                        self._loops_finalizing.discard(effective_loop_id)
                        self._broadcast_turn_generation.pop(effective_loop_id, None)
                if client_id:
                    await d._session_manager.release_loop_ownership(client_id)
                await self._release_query_admission(effective_loop_id)
                self._clear_loop_cancel_armed_state(effective_loop_id)
                return

            # Once the stream has started (past the race window), a recorded
            # pending cancel is obsolete — the orchestrator will cancel the
            # now-registered asyncio task directly.
            self._clear_loop_cancel_armed_state(effective_loop_id)

            chunk_count = 0
            timeout_minutes = d._daemon_config.max_query_duration_minutes
            timeout_enabled = timeout_minutes > 0
            timeout_seconds = timeout_minutes * 60 if timeout_enabled else None
            warning_threshold = timeout_seconds * 0.8 if timeout_enabled else None
            start_time = asyncio.get_event_loop().time() if timeout_enabled else None
            warning_sent = False

            try:
                loop_meta: dict[str, Any] = {}
                if effective_loop_id:
                    loop_meta = (
                        await d._persistence_manager.get_loop_metadata(effective_loop_id) or {}
                    )

                stream_kwargs: dict[str, Any] = {"thread_id": thread_id}
                if autonomous:
                    stream_kwargs["autonomous"] = True
                    if max_iterations is not None:
                        stream_kwargs["max_iterations"] = max_iterations
                if preferred_subagent is not None:
                    stream_kwargs["preferred_subagent"] = preferred_subagent
                if clarification_mode is not None:
                    stream_kwargs["clarification_mode"] = clarification_mode

                # All queries use subprocess isolation via the runner factory.
                _runner_key = effective_loop_id or thread_id

                from soothe.protocols.runner import LoopRunRequest

                # RFC-621: Use current_workspace (container path) not client_workspace (host path).
                # The router already translated client_workspace → current_workspace at loop_new.
                run_request = LoopRunRequest(
                    loop_id=effective_loop_id or thread_id,
                    thread_id=thread_id,
                    user_input=effective_text,
                    client_workspace=loop_meta.get("current_workspace")
                    or loop_meta.get("client_workspace"),
                    user_id=loop_meta.get("user_id") or loop_meta.get("user"),
                    client_workspace_id=loop_meta.get("client_workspace_id"),
                    workspace_mapping=loop_meta.get("workspace_mapping"),
                    autonomous=stream_kwargs.get("autonomous", False),
                    max_iterations=stream_kwargs.get("max_iterations"),
                    preferred_subagent=stream_kwargs.get("preferred_subagent"),
                    model=model,
                    model_params=model_params or {},
                    router_profile=profile_name,
                    clarification_mode=stream_kwargs.get("clarification_mode"),
                    clarification_answer=clarification_answer,
                    clarification_answers=clarification_answers,
                )
                run_workspace = run_request.resolve_workspace_path()
                loop_runner = d._runner_factory.create_runner(_runner_key)
                self._active_runners[_runner_key] = _ActiveLoopRunner(
                    runner=loop_runner,
                    turn_generation=turn_generation,
                )
                logger.info(
                    "Query stream dispatching loop=%s checkpoint=%s",
                    effective_loop_id or "?",
                    thread_id[:16] if thread_id else "?",
                )

                async def _stream_chunks() -> Any:
                    async for item in loop_runner.run(run_request):
                        yield item

                delivery_mode = (
                    d._session_manager.get_stream_delivery(
                        client_id=client_id,
                        loop_id=effective_loop_id,
                    )
                    if effective_loop_id or client_id
                    else "adaptive"
                )
                # Get streaming config parameters (RFC-614)
                streaming_cfg = self._get_output_streaming_config(d)
                coalescer = StreamDeliveryCoalescer(
                    delivery_mode,
                    adaptive_threshold_chars=streaming_cfg.get("adaptive_threshold_chars", 1000),
                    adaptive_block_chars=streaming_cfg.get("adaptive_block_chars", 500),
                    adaptive_block_interval_ms=streaming_cfg.get("adaptive_block_interval_ms", 250),
                    file_output_threshold_chars=streaming_cfg.get("file_output_threshold_chars", 0),
                    file_output_preview_chars=streaming_cfg.get("file_output_preview_chars", 500),
                    file_output_dir=streaming_cfg.get("file_output_dir"),
                    workspace=run_workspace,
                    message_coalesce_enabled=streaming_cfg.get("message_coalesce_enabled", True),
                    coalesce_interval_ms=streaming_cfg.get("streaming_interval_ms", 100),
                    tool_batch_enabled=streaming_cfg.get("tool_batch_enabled", True),
                    tool_batch_interval_ms=streaming_cfg.get("tool_batch_interval_ms", 200),
                    suppress_redundant_stream_tool_updates=streaming_cfg.get(
                        "suppress_redundant_stream_tool_updates", True
                    ),
                    skip_redundant_tool_message_wire=streaming_cfg.get(
                        "skip_redundant_tool_message_wire", False
                    ),
                )

                async def _process_stream() -> None:
                    nonlocal chunk_count, warning_sent, full_response_chars, goal_completion_chars
                    # Scope cancellation to this stream task only. The daemon keeps a
                    # single ``_current_query_task`` pointer that concurrent queries
                    # overwrite; checking that global slot caused unrelated finished
                    # queries to abort still-running streams (loop 3e1c incident).
                    stream_task = asyncio.current_task()

                    async for chunk in _stream_chunks():
                        if stream_task is not None and stream_task.cancelled():
                            logger.info(
                                "Stream loop detected cancellation for loop=%s, stopping",
                                (effective_loop_id or thread_id or "?")[:16],
                            )
                            break

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
                                    await self._broadcast_loop_message(
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
                            # IG-477: Apply bounded accumulation to prevent memory leak
                            text_parts = extract_text_from_ai_message(msg)
                            for part in text_parts:
                                if full_response_chars + len(part) < _MAX_FULL_RESPONSE_CHARS:
                                    full_response.append(part)
                                    full_response_chars += len(part)
                            from soothe_sdk.ux.loop_stream import assistant_output_phase

                            if assistant_output_phase(msg) == "goal_completion":
                                for part in text_parts:
                                    if goal_completion_chars + len(part) < _MAX_FULL_RESPONSE_CHARS:
                                        goal_completion_response.append(part)
                                        goal_completion_chars += len(part)
                            # Detect phase-tagged loop assistant output so the
                            # finally block can skip the legacy concat row.
                            if not phase_tagged_assistant_written[0]:
                                if assistant_output_phase(msg):
                                    phase_tagged_assistant_written[0] = True

                        if effective_loop_id:
                            ns_tuple = tuple(namespace) if namespace else ()
                            outputs = list(coalescer.ingest(ns_tuple, mode, data))
                            if outputs:
                                await self._broadcast_coalescer_outputs(
                                    effective_loop_id,
                                    outputs,
                                    coalescer=coalescer,
                                )

                    flush_outputs = list(coalescer.flush())
                    if effective_loop_id and flush_outputs:
                        await self._broadcast_coalescer_outputs(
                            effective_loop_id,
                            flush_outputs,
                            coalescer=coalescer,
                        )

                    turn_completed_via_coalescer = coalescer.consume_turn_complete_pending()
                    logger.debug(
                        "runner.astream() completed, total chunks: %d, turn_completed=%s",
                        chunk_count,
                        turn_completed_via_coalescer,
                    )
                    await _ensure_turn_stream_end()

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
                from soothe.foundation.workspace import FrameworkFilesystem

                FrameworkFilesystem.clear_current_workspace()

                # Cancel the running query
                if d._current_query_task:
                    d._current_query_task.cancel()

                if effective_loop_id:
                    await self._broadcast_loop_message(
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
            except asyncio.CancelledError:
                logger.info("Query cancelled by user")
                turn_cancelled = True
                from soothe.foundation.workspace import FrameworkFilesystem

                FrameworkFilesystem.clear_current_workspace()
                raise
            except Exception as exc:
                logger.exception("Daemon query error")
                if effective_loop_id:
                    await self._broadcast_loop_message(
                        effective_loop_id,
                        {
                            "type": "event",
                            "namespace": [],
                            "mode": "custom",
                            "data": emit_error_event(exc),
                        },
                    )
            finally:
                # Turn ownership guards every shared-state teardown below: a
                # superseded turn (Ctrl+C + queued goal admitted a successor on
                # the same loop) must not evict the successor's task, admission,
                # runner, or stream registration. ``_unregister_query_task`` is
                # identity-scoped since successors reuse the checkpoint thread_id.
                stream_task = asyncio.current_task()
                owns_turn = self._owns_turn(effective_loop_id, turn_generation)
                # Mark finalizing before releasing admission so the next admit
                # cannot slip in during drain/stream.end/idle (phase 4).
                if owns_turn and effective_loop_id:
                    self._loops_finalizing.add(effective_loop_id)
                try:
                    await self._unregister_query_task(thread_id, stream_task)
                    if owns_turn:
                        await self._release_query_admission(effective_loop_id)
                        active = self._active_runners.pop(effective_loop_id or thread_id, None)
                        if active is not None and active.turn_generation == turn_generation:
                            loop_runner_cleanup = active.runner
                        else:
                            loop_runner_cleanup = None
                            if active is not None and effective_loop_id:
                                self._active_runners[effective_loop_id] = active
                    else:
                        loop_runner_cleanup = None
                    if loop_runner_cleanup is not None:
                        try:
                            await loop_runner_cleanup.cancel()
                        except Exception:
                            logger.debug(
                                "QueryEngine: loop_runner.cancel during stream finally failed",
                                exc_info=True,
                            )
                    if owns_turn and effective_loop_id:
                        d._active_stream_loop_ids.discard(effective_loop_id)  # Bug 4.3

                    # IG-054: Moved post-query logic here since we don't await task
                    final_thread_id = d._runner.current_thread_id or ""
                    final_logger_handle: ThreadLogger | None = None
                    # Phase-tagged conversation rows (plan_direct, goal_completion,
                    # etc.) written by ``_log_message_event`` are the canonical
                    # record of the assistant's user-visible output. The legacy
                    # ``log_assistant_response("".join(full_response))`` concatenates
                    # plan_direct text + ToolMessage outputs + goal_completion
                    # fragments into a single malformed assistant card — surface it
                    # only when nothing phase-tagged was written (autopilot bundles,
                    # non-loop turns, etc. that bypass the per-phase emit paths).
                    write_legacy_assistant_row = (
                        bool(full_response) and not phase_tagged_assistant_written[0]
                    )
                    if final_thread_id and final_thread_id != thread_id:
                        final_logger = ThreadLogger(
                            thread_id=final_thread_id,
                            retention_days=d._config.observability.thread_logging_retention_days,
                            max_size_mb=d._config.observability.thread_logging_max_size_mb,
                        )
                        final_logger.log_user_input(effective_text)
                        if write_legacy_assistant_row:
                            final_logger.log_assistant_response("".join(full_response))
                        final_logger_handle = final_logger
                    elif write_legacy_assistant_row:
                        thread_logger.log_assistant_response("".join(full_response))

                    # Flush ThreadLogger's write buffer. Records (especially the
                    # ``phase=goal_completion`` conversation row written by
                    # ``_log_message_event`` for the final assistant chunk, and
                    # the ``log_assistant_response`` write above) only flush on
                    # the NEXT write or after the 1-second interval elapses;
                    # once the loop ends no further writes arrive on this thread,
                    # so without an explicit flush the tail records stay stuck in
                    # memory and resume rendering loses the final answer.
                    try:
                        thread_logger.flush()
                    except Exception:
                        logger.debug("ThreadLogger flush failed for primary log", exc_info=True)
                    if final_logger_handle is not None:
                        try:
                            final_logger_handle.flush()
                        except Exception:
                            logger.debug(
                                "ThreadLogger flush failed for final_logger", exc_info=True
                            )

                    if final_thread_id:
                        await d._runner.touch_thread_activity_timestamp(final_thread_id)

                    # Wire terminals must re-check ownership after every await: a
                    # successor can admit during delivery drain and must not
                    # receive the prior turn's stream.end / idle.
                    # Drain first, then emit stream.end only if still owning.
                    # Goal display freeze remains safe for superseded turns.
                    if effective_loop_id and owns_turn:
                        if self._owns_turn(effective_loop_id, turn_generation):
                            drain_cfg = self._get_output_streaming_config(d)
                            await d._session_manager.await_loop_delivery_drained(
                                effective_loop_id,
                                batch_timeout_s=drain_cfg.get("streaming_interval_ms", 100)
                                / 1000.0,
                            )

                        still_owns = self._owns_turn(effective_loop_id, turn_generation)
                        if turn_cancelled and still_owns:
                            await self._mark_active_context_goals_cancelled(
                                effective_loop_id,
                                reason="user_cancelled",
                            )
                        # RFC-631: freeze live card tail into a goal snapshot before idle.
                        card_manager = getattr(d, "_card_manager", None)
                        if card_manager is not None:
                            try:
                                # Cancelled turns should not infer a synthetic "completion"
                                # summary from the live ledger.
                                goal_completion_text = ""
                                if not turn_cancelled:
                                    goal_completion_text = "".join(goal_completion_response).strip()
                                    if not goal_completion_text:
                                        goal_completion_text = (
                                            await _peek_goal_completion_from_ledger(
                                                card_manager,
                                                effective_loop_id,
                                            )
                                        )
                                await card_manager.freeze_goal_display(
                                    effective_loop_id,
                                    goal_text=effective_text,
                                    goal_completion=goal_completion_text,
                                    status="cancelled" if turn_cancelled else "completed",
                                )
                            except Exception:
                                logger.warning(
                                    "Goal display snapshot freeze failed for loop %s",
                                    effective_loop_id[:16],
                                    exc_info=True,
                                )

                        if self._owns_turn(effective_loop_id, turn_generation):
                            await _ensure_turn_stream_end()
                            # Long-lived loop_events stays open across goals.
                            # Turn boundary is stream.end + idle (not subscription complete).
                            if self._owns_turn(effective_loop_id, turn_generation):
                                await self._broadcast_loop_message(
                                    effective_loop_id,
                                    {"type": "status", "state": "idle"},
                                    turn_generation=turn_generation,
                                )
                            else:
                                logger.debug(
                                    "Skipped stale turn idle "
                                    "(loop=%s gen=%s superseded during finalize)",
                                    effective_loop_id[:16],
                                    turn_generation,
                                )
                        else:
                            logger.debug(
                                "Skipped stale turn stream.end/idle "
                                "(loop=%s gen=%s superseded before/during finalize)",
                                effective_loop_id[:16],
                                turn_generation,
                            )
                    elif effective_loop_id and not owns_turn:
                        logger.debug(
                            "Skipped stale turn stream.end/idle "
                            "(loop=%s gen=%s superseded before finalize)",
                            effective_loop_id[:16],
                            turn_generation,
                        )

                    if client_id and self._owns_turn(effective_loop_id, turn_generation):
                        await d._session_manager.release_loop_ownership(client_id)
                    # Only clear the shared pointer if a successor turn has not
                    # already claimed it (superseded turns must not null it out).
                    async with d._query_state_lock:
                        if d._current_query_task is stream_task:
                            d._current_query_task = None
                finally:
                    if effective_loop_id:
                        self._loops_finalizing.discard(effective_loop_id)
                        self._broadcast_turn_generation.pop(effective_loop_id, None)

        try:
            task = asyncio.create_task(_run_stream())
            await self._register_query_task(thread_id, task)
            # Broadcast ``running`` only after the task is registered so a
            # concurrent ``/cancel`` can resolve it (RFC-221 cancel race fix).
            if effective_loop_id:
                await self._broadcast_loop_message(
                    effective_loop_id,
                    {"type": "status", "state": "running"},
                    turn_generation=turn_generation,
                )
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
            await self._unregister_query_task(thread_id)
            await self._release_query_admission(effective_loop_id)
            if client_id:
                await d._session_manager.release_loop_ownership(client_id)
            raise

    async def _start_intent_hint_background(
        self,
        *,
        text: str,
        thread_id: str,
        effective_loop_id: str,
        client_id: str | None,
        intent_hint_value: str,
        model: str | None,
        model_params: dict[str, Any] | None,
        attachments: list[dict[str, str]] | None,
        thread_logger: ThreadLogger,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str | None = None,
        response_schema_strict: bool | None = None,
        turn_generation: int = 0,
    ) -> None:
        """Spawn background task for ``intent_hint`` turns (no agent subprocess)."""
        d = self._daemon

        async def _run_intent_hint() -> None:
            await self._run_intent_hint_body(
                text=text,
                thread_id=thread_id,
                effective_loop_id=effective_loop_id,
                client_id=client_id,
                intent_hint_value=intent_hint_value,
                model=model,
                model_params=model_params,
                attachments=attachments,
                thread_logger=thread_logger,
                response_schema=response_schema,
                response_schema_name=response_schema_name,
                response_schema_strict=response_schema_strict,
                turn_generation=turn_generation,
            )

        try:
            task = asyncio.create_task(_run_intent_hint())
            await self._register_query_task(thread_id, task)
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            logger.info("Intent-hint task cancelled during creation")
            d._runner.set_current_thread_id(None)
            raise
        except Exception:
            logger.exception("Failed to create intent-hint task")
            await self._unregister_query_task(thread_id)
            await self._release_query_admission(effective_loop_id)
            if client_id:
                await d._session_manager.release_loop_ownership(client_id)
            raise

    async def _run_intent_hint_body(
        self,
        *,
        text: str,
        thread_id: str,
        effective_loop_id: str,
        client_id: str | None,
        intent_hint_value: str,
        model: str | None,
        model_params: dict[str, Any] | None,
        attachments: list[dict[str, str]] | None,
        thread_logger: ThreadLogger,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str | None = None,
        response_schema_strict: bool | None = None,
        turn_generation: int = 0,
    ) -> None:
        """Execute one intent-hint call and broadcast a single assistant ``messages`` event."""
        d = self._daemon
        self._broadcast_turn_generation[effective_loop_id] = turn_generation

        if client_id and effective_loop_id:
            await d._session_manager.claim_loop_ownership(client_id, effective_loop_id)
            subscribed = await d._session_manager.subscribe_loop(client_id, effective_loop_id)
            if not subscribed:
                logger.warning(
                    "Client %s not found for loop %s subscription (intent-hint turn)",
                    client_id[:8] if client_id else "?",
                    effective_loop_id[:8],
                )

        await self._broadcast_loop_message(
            effective_loop_id,
            {"type": "status", "state": "running"},
            turn_generation=turn_generation,
        )

        user_log_line = text.strip() if text.strip() else f"[{intent_hint_value}]"
        thread_logger.log_user_input(user_log_line)

        await d._runner.touch_thread_activity_timestamp(thread_id)
        st_activity = d._thread_registry.get(thread_id)
        if st_activity:
            st_activity.last_activity = datetime.now(UTC)

        try:
            answer = await run_intent_hint_turn(
                d._config,
                intent_hint=intent_hint_value,
                user_text=text,
                model=model,
                model_params=model_params,
                session_id=thread_id,
                attachments=list(attachments or []) or None,
                response_schema=response_schema,
                response_schema_name=response_schema_name,
                response_schema_strict=response_schema_strict,
            )

            from soothe.foundation.sloop.utils.messages import LoopAIMessage

            phase = intent_hint_value
            ai_flat = _serialize_for_json(
                LoopAIMessage(content=answer, phase=phase, thread_id=thread_id)
            )
            await self._broadcast_loop_message(
                effective_loop_id,
                {
                    "type": "event",
                    "namespace": [],
                    "mode": "messages",
                    "data": (ai_flat, {}),
                },
            )
            thread_logger.log_assistant_response(answer)
        except asyncio.CancelledError:
            logger.info("Intent-hint turn cancelled")
            raise
        except Exception as exc:
            logger.exception("Intent-hint turn failed")
            await self._broadcast_loop_message(
                effective_loop_id,
                {
                    "type": "event",
                    "namespace": [],
                    "mode": "custom",
                    "data": emit_error_event(exc),
                },
            )
        finally:
            direct_task = asyncio.current_task()
            await self._unregister_query_task(thread_id, direct_task)
            self._loops_finalizing.add(effective_loop_id)
            try:
                await self._release_query_admission(effective_loop_id)
                try:
                    thread_logger.flush()
                except Exception:
                    logger.debug("ThreadLogger flush failed in direct turn finally", exc_info=True)
                if self._owns_turn(effective_loop_id, turn_generation):
                    await self._emit_turn_stream_end(
                        effective_loop_id,
                        turn_generation=turn_generation,
                    )
                    await self._broadcast_loop_message(
                        effective_loop_id,
                        {"type": "status", "state": "idle"},
                        turn_generation=turn_generation,
                    )
            finally:
                self._loops_finalizing.discard(effective_loop_id)
                self._broadcast_turn_generation.pop(effective_loop_id, None)
            if client_id:
                await d._session_manager.release_loop_ownership(client_id)
            async with d._query_state_lock:
                if d._current_query_task is direct_task:
                    d._current_query_task = None

    async def cancel_loop(self, loop_id: str) -> None:
        """Cancel running query tasks bound to ``loop_id`` (IG-408).

        Signals cancellation immediately (runner.cancel() called before return),
        then kicks off async background task that guarantees completion via
        retry loop and force kill fallback.

        Returns immediately after signaling; completion is guaranteed in background.
        """
        lidq = str(loop_id or "").strip()
        if not lidq:
            logger.warning("cancel_loop called with empty loop_id; ignoring (no cancellation)")
            return

        if self.is_cancel_in_progress(lidq):
            logger.debug(
                "Duplicate cancel for loop %s while cancel in progress; ignoring",
                lidq[:16],
            )
            return

        active_tasks = self.collect_active_tasks_for_loop(lidq)
        has_runner = lidq in self._active_runners
        if not active_tasks and not has_runner and not self._should_arm_pending_cancel(lidq):
            logger.debug("Cancel for idle loop %s; no work to stop", lidq[:16])
            return

        # Arm ``_pending_cancels`` only during the pre-registration race window
        # (early ``running`` or admitted query, before the asyncio task exists).
        # Duplicate post-cancel ``/cancel`` must not poison the next submit.
        if self._should_arm_pending_cancel(lidq):
            self._pending_cancels.add(lidq)

        # RFC-221: signal the pool/local subprocess runner *before* return.
        # This ensures cooperative cancellation starts immediately, even though
        # retry/force-kill logic runs in background.
        active = self._active_runners.get(lidq)
        if active is not None:
            try:
                await active.runner.cancel()
            except Exception:
                logger.debug(
                    "cancel_loop: loop_runner.cancel failed loop_id=%s",
                    lidq[:16],
                    exc_info=True,
                )

        # Broadcast cancellation notice immediately
        await self._daemon._broadcast(
            {
                "type": "command_response",
                "content": "[yellow]Cancellation requested.[/yellow]",
                "loop_id": lidq,
            }
        )

        # Use async orchestrator for guaranteed completion in background
        if self._cancel_orchestrator is None:
            self._cancel_orchestrator = AsyncCancelOrchestrator(self._daemon, self)

        orchestrator = self._cancel_orchestrator
        await orchestrator.start_async_cancel(lidq, already_signaled=True)
        # Returns immediately - retry/force-kill runs in background

    async def ensure_active_checkpoint_thread_id(self) -> str:
        """Ensure the runner has a concrete LangGraph checkpoint id."""
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
