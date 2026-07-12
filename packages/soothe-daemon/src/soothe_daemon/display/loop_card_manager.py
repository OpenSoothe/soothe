"""Per-loop card ledger lifecycle, real-time binding, and reattach replay.

IG-535 Optimization 4: Uses dedicated card-bind executor to isolate from
asyncio.to_thread pool, preventing contention under concurrent loops.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage
from soothe_sdk.display import card_binder
from soothe_sdk.display.card_ledger import cards_to_mutations
from soothe_sdk.display.snapshot_collapser import (
    build_goal_snapshot,
    fold_display_cards,
    split_cards_by_user_segments,
)
from soothe_sdk.display.snapshot_types import GoalDisplaySnapshot
from soothe_sdk.display.transcript_types import MessageData, MessageType

from soothe_daemon.display.loop_card_ledger import LoopCardLedger
from soothe_daemon.display.loop_history_probe import filter_derivable_log_events

if TYPE_CHECKING:
    from soothe_sdk.display.transcript_types import MessageData

logger = logging.getLogger(__name__)

CARD_REPLAY_BEGIN = "card.replay_begin"
CARD_CREATED = "card.created"
CARD_REPLAY_END = "card.replay_end"

_DERIVABLE_CUSTOM_KINDS = frozenset({"event", "tool_call", "tool_result", "conversation"})

_CARD_FLUSH_DEBOUNCE_MS_DEFAULT = 200
_STREAM_DEGRADED_REASON = "card_ingest_overflow"

# Cumulative overflow frames queued per loop (zero-loss deque path; not drops).
_card_ingest_overflow_total: dict[str, int] = defaultdict(int)


def get_card_ingest_overflow_metrics() -> dict[str, int]:
    """Return cumulative card-ingest overflow counts keyed by ``loop_id``."""
    return dict(_card_ingest_overflow_total)


def reset_card_ingest_overflow_metrics() -> None:
    """Clear overflow counters (tests only)."""
    _card_ingest_overflow_total.clear()


# IG-535 Optimization 4: Dedicated executor for card binding (isolated from to_thread pool)
_card_bind_executor: ThreadPoolExecutor | None = None
_card_bind_max_workers = 4


def _get_card_bind_executor() -> ThreadPoolExecutor:
    """Return the dedicated card-bind executor (lazily initialized).

    IG-535: Separate from asyncio.to_thread pool to prevent contention
    when N concurrent loops all call card binding simultaneously.
    """
    global _card_bind_executor
    if _card_bind_executor is None:
        _card_bind_executor = ThreadPoolExecutor(
            max_workers=_card_bind_max_workers,
            thread_name_prefix="soothe-card-bind",
        )
    return _card_bind_executor


def shutdown_card_bind_executor() -> None:
    """Shutdown the card-bind executor on daemon stop."""
    global _card_bind_executor
    if _card_bind_executor is not None:
        _card_bind_executor.shutdown(wait=False)
        _card_bind_executor = None


@dataclass
class _BindingBuffers:
    messages: list[Any] = field(default_factory=list)
    log_events: list[dict[str, Any]] = field(default_factory=list)


_CARD_BIND_QUEUE_MAXSIZE = 500  # IG-534 §2.3: bounded per-loop ingest backlog


@dataclass
class _LoopIngestWorker:
    queue: asyncio.Queue[tuple[tuple[str, ...], str, Any] | None]
    task: asyncio.Task[None]
    overflow: deque[tuple[tuple[str, ...], str, Any]] = field(default_factory=deque)


@dataclass
class _LoopFlushScheduler:
    task: asyncio.Task[None] | None = None


class LoopCardManager:
    """Owns per-loop ``LoopCardLedger`` instances and real-time card binding."""

    def __init__(
        self,
        daemon: Any,
        *,
        ingest_queue_maxsize: int = _CARD_BIND_QUEUE_MAXSIZE,
        flush_debounce_ms: int = _CARD_FLUSH_DEBOUNCE_MS_DEFAULT,
    ) -> None:
        self._daemon = daemon
        self._ledgers: dict[str, LoopCardLedger] = {}
        self._buffers: dict[str, _BindingBuffers] = defaultdict(_BindingBuffers)
        self._ingest_workers: dict[str, _LoopIngestWorker] = {}
        self._flush_schedulers: dict[str, _LoopFlushScheduler] = defaultdict(_LoopFlushScheduler)
        self._ingest_queue_maxsize = max(1, int(ingest_queue_maxsize))
        self._flush_debounce_s = max(0.0, int(flush_debounce_ms) / 1000.0)
        self._ingest_lock = asyncio.Lock()
        self._stream_degraded_sent: set[str] = set()

    def overflow_depth(self, loop_id: str) -> int:
        """Current overflow deque depth for ``loop_id`` (0 when no worker)."""
        worker = self._ingest_workers.get(loop_id)
        if worker is None:
            return 0
        return len(worker.overflow)

    async def _notify_card_ingest_pressure(self, loop_id: str, overflow_depth: int) -> None:
        """Emit ``stream_degraded`` once per backpressure episode (RFC-450 §14)."""
        if overflow_depth <= 0 or loop_id in self._stream_degraded_sent:
            return
        self._stream_degraded_sent.add(loop_id)
        broadcast = getattr(self._daemon, "_broadcast", None)
        if broadcast is None:
            return
        total = _card_ingest_overflow_total.get(loop_id, 0)
        msg = {
            "type": "event",
            "loop_id": loop_id,
            "mode": "custom",
            "data": {
                "type": "stream_degraded",
                "reason": _STREAM_DEGRADED_REASON,
                "dropped_count": 0,
                "overflow_depth": overflow_depth,
                "overflow_total": total,
                "recoverable": True,
            },
        }
        try:
            await broadcast(msg)
        except Exception:
            logger.debug("Failed to emit stream_degraded for loop %s", loop_id, exc_info=True)

    def _maybe_clear_stream_degraded(self, loop_id: str, worker: _LoopIngestWorker) -> None:
        """Allow a new degradation signal after backlog drains."""
        if worker.overflow:
            return
        if worker.queue.qsize() >= max(1, int(worker.queue.maxsize * 0.5)):
            return
        self._stream_degraded_sent.discard(loop_id)

    async def stop_for_loop(self, loop_id: str) -> None:
        """Drop in-memory ledger and binding buffers for ``loop_id``."""
        await self._shutdown_ingest_worker(loop_id)
        await self._cancel_debounced_flush(loop_id)
        state = self._buffers.get(loop_id)
        if state is not None and (state.messages or state.log_events):
            await self._flush_buffers_to_ledger(loop_id, state)
        self._ledgers.pop(loop_id, None)
        self._buffers.pop(loop_id, None)
        self._flush_schedulers.pop(loop_id, None)
        self._stream_degraded_sent.discard(loop_id)

    async def _shutdown_ingest_worker(self, loop_id: str) -> None:
        async with self._ingest_lock:
            worker_state = self._ingest_workers.pop(loop_id, None)
        if worker_state is None:
            return
        task = worker_state.task
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _open_ledger(self, loop_id: str) -> LoopCardLedger:
        ledger = self._ledgers.get(loop_id)
        if ledger is None:
            ledger = LoopCardLedger(loop_id=loop_id)
            self._ledgers[loop_id] = ledger
        await ledger.ensure_loaded()
        return ledger

    async def ensure_for_loop(self, loop_id: str) -> LoopCardLedger:
        """Return the ledger for ``loop_id``, loading persisted mutations from DB."""
        return await self._open_ledger(loop_id)

    async def is_display_empty(self, loop_id: str) -> bool:
        """Return True when the persisted ledger has no display cards."""
        ledger = await self._open_ledger(loop_id)
        return ledger.card_count() == 0

    async def record_user_prompt(self, loop_id: str, prompt: str) -> None:
        """Bind the initial user prompt card when a loop turn starts."""
        text = str(prompt or "").strip()
        if not text:
            return
        state = self._buffers[loop_id]
        state.messages = [m for m in state.messages if not isinstance(m, HumanMessage)]
        state.messages.insert(0, HumanMessage(content=text))
        await self._flush_buffers_to_ledger(loop_id, state)

    async def on_event(self, loop_id: str, event: dict[str, Any]) -> None:
        """Apply one derivable activity-log style event to the ledger."""
        rows = filter_derivable_log_events([event])
        if not rows:
            return
        state = self._buffers[loop_id]
        state.log_events.append(rows[0])
        await self._flush_buffers_to_ledger(loop_id, state)

    async def ingest_stream_tuple(
        self,
        loop_id: str,
        namespace: tuple[str, ...],
        mode: str,
        data: Any,
    ) -> None:
        """Queue one stream tuple for background card binding (IG-534 §2.3).

        Never blocks the daemon stream hot path. Failures are logged in the
        per-loop ingest worker.
        """
        if mode == "updates":
            return
        queue = await self._ensure_ingest_queue(loop_id)
        worker = self._ingest_workers[loop_id]
        item = (namespace, mode, data)
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            worker.overflow.append(item)
            _card_ingest_overflow_total[loop_id] += 1
            depth = len(worker.overflow)
            if depth == 1 or depth % 200 == 0:
                logger.debug(
                    "Card ingest overflow depth=%d (queue=%d/%d) loop=%s total=%d",
                    depth,
                    queue.qsize(),
                    queue.maxsize,
                    loop_id,
                    _card_ingest_overflow_total[loop_id],
                )
            if depth == 1 or depth % 200 == 0:
                asyncio.create_task(
                    self._notify_card_ingest_pressure(loop_id, depth),
                    name=f"soothe-card-pressure-{loop_id[:16]}",
                )

    async def _ensure_ingest_queue(self, loop_id: str) -> asyncio.Queue:
        async with self._ingest_lock:
            worker_state = self._ingest_workers.get(loop_id)
            if worker_state is not None:
                return worker_state.queue
            queue: asyncio.Queue[tuple[tuple[str, ...], str, Any] | None] = asyncio.Queue(
                maxsize=self._ingest_queue_maxsize
            )
            overflow: deque[tuple[tuple[str, ...], str, Any]] = deque()
            task = asyncio.create_task(
                self._ingest_worker(loop_id, queue, overflow),
                name=f"soothe-card-ingest-{loop_id[:16]}",
            )
            self._ingest_workers[loop_id] = _LoopIngestWorker(
                queue=queue,
                task=task,
                overflow=overflow,
            )
            return queue

    @staticmethod
    async def _next_ingest_item(
        queue: asyncio.Queue[tuple[tuple[str, ...], str, Any] | None],
        overflow: deque[tuple[tuple[str, ...], str, Any]],
    ) -> tuple[tuple[str, ...], str, Any] | None:
        """Drain overflow first, then the bounded queue (zero-loss ingest)."""
        if overflow:
            return overflow.popleft()
        try:
            return queue.get_nowait()
        except asyncio.QueueEmpty:
            return await queue.get()

    async def _ingest_worker(
        self,
        loop_id: str,
        queue: asyncio.Queue[tuple[tuple[str, ...], str, Any] | None],
        overflow: deque[tuple[tuple[str, ...], str, Any]],
    ) -> None:
        try:
            while True:
                item = await self._next_ingest_item(queue, overflow)
                if item is None:
                    break
                namespace, mode, data = item
                try:
                    await self._ingest_stream_tuple_now(loop_id, namespace, mode, data)
                except Exception:
                    logger.exception("Card ingest worker failed for loop %s", loop_id)
                worker_state = self._ingest_workers.get(loop_id)
                if worker_state is not None:
                    self._maybe_clear_stream_degraded(loop_id, worker_state)
        except asyncio.CancelledError:
            pending: list[tuple[tuple[str, ...], str, Any] | None] = list(overflow)
            overflow.clear()
            with contextlib.suppress(asyncio.QueueEmpty):
                while True:
                    pending.append(queue.get_nowait())
            for item in pending:
                if item is None:
                    continue
                namespace, mode, data = item
                with contextlib.suppress(Exception):
                    await self._ingest_stream_tuple_now(loop_id, namespace, mode, data)
            raise

    async def _ingest_stream_tuple_now(
        self,
        loop_id: str,
        namespace: tuple[str, ...],
        mode: str,
        data: Any,
    ) -> None:
        """Apply one stream tuple to in-memory buffers and flush to the ledger."""
        del namespace  # reserved for future namespace-aware binding
        if mode == "updates":
            return
        state = self._buffers[loop_id]
        changed = False
        if mode == "messages" and isinstance(data, (tuple, list)) and len(data) == 2:
            msg_wire = data[0]
            if isinstance(msg_wire, dict):
                changed = self._ingest_message_wire(state, msg_wire)
        elif mode == "custom" and isinstance(data, dict):
            kind = data.get("kind")
            if kind in _DERIVABLE_CUSTOM_KINDS:
                state.log_events.append(data)
                changed = True
        if changed:
            await self._schedule_debounced_flush(loop_id)

    @staticmethod
    def _custom_event_type(data: dict[str, Any]) -> str | None:
        event_type = data.get("type")
        if isinstance(event_type, str) and event_type.strip():
            return event_type.strip()
        nested = data.get("data")
        if isinstance(nested, dict):
            inner = nested.get("type")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
        return None

    async def _cancel_debounced_flush(self, loop_id: str) -> None:
        sched = self._flush_schedulers.get(loop_id)
        if sched is None or sched.task is None:
            return
        task = sched.task
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        sched.task = None

    async def _schedule_debounced_flush(self, loop_id: str) -> None:
        """Coalesce rapid stream ingests into one card-bind pass per debounce window."""
        if self._flush_debounce_s <= 0:
            state = self._buffers[loop_id]
            await self._flush_buffers_to_ledger(loop_id, state)
            return

        await self._cancel_debounced_flush(loop_id)
        debounce_s = self._effective_flush_debounce_s(loop_id)

        async def _debounced() -> None:
            try:
                await asyncio.sleep(debounce_s)
                state = self._buffers[loop_id]
                await self._flush_buffers_to_ledger(loop_id, state)
            except asyncio.CancelledError:
                raise
            finally:
                sched = self._flush_schedulers.get(loop_id)
                if sched is not None:
                    sched.task = None

        self._flush_schedulers[loop_id].task = asyncio.create_task(
            _debounced(),
            name=f"soothe-card-flush-{loop_id[:16]}",
        )

    def _effective_flush_debounce_s(self, loop_id: str) -> float:
        """Widen debounce when ingest backlog exceeds 80% capacity (IG-546)."""
        base = self._flush_debounce_s
        worker = self._ingest_workers.get(loop_id)
        if worker is None or worker.queue.maxsize <= 0:
            return base
        pending = worker.queue.qsize() + len(worker.overflow)
        if pending >= int(worker.queue.maxsize * 0.8):
            return min(base * 2.5, 1.0)
        return base

    @staticmethod
    def _ingest_message_wire(state: _BindingBuffers, msg_wire: dict[str, Any]) -> bool:
        from soothe_sdk.client.wire import (
            flatten_enveloped_message_dict,
            messages_from_wire_dicts,
        )

        flat = flatten_enveloped_message_dict(msg_wire)
        chunk_pos = flat.get("chunk_position")
        if chunk_pos not in (None, "last"):
            return False
        try:
            msgs = messages_from_wire_dicts([flat])
        except Exception:
            logger.debug("Failed to parse stream message for card binding", exc_info=True)
            return False
        if not msgs:
            return False
        state.messages.extend(msgs)
        return True

    async def _flush_buffers_to_ledger(self, loop_id: str, state: _BindingBuffers) -> None:
        """Flush buffers to ledger using dedicated card-bind executor.

        IG-535 Optimization 4: Uses isolated ThreadPoolExecutor instead of
        asyncio.to_thread to prevent contention with general thread pool.
        """
        executor = _get_card_bind_executor()
        loop = asyncio.get_running_loop()

        # Run binding in dedicated executor (not asyncio.to_thread pool)
        cards = await loop.run_in_executor(
            executor,
            self._bind_cards,
            state.messages,
            state.log_events,
        )
        ledger = await self._open_ledger(loop_id)
        mutations = cards_to_mutations(cards) if cards else []
        if mutations:
            await ledger.replace_with(mutations)

    @staticmethod
    def _bind_cards(
        messages: list[Any],
        log_events: list[dict[str, Any]],
    ) -> list[MessageData]:
        cognition_replay: list[MessageData] = []
        if log_events:
            cognition_replay = card_binder.collect_cognition_card_replay(log_events)
        visible_messages = [
            message
            for message in messages
            if not card_binder.is_loop_internal_checkpoint_message(message)
        ]
        if visible_messages:
            return card_binder.convert_messages_to_data(
                visible_messages,
                cognition_card_replay=cognition_replay if cognition_replay else None,
            )
        if log_events:
            return card_binder.convert_loop_events_to_data(log_events)
        return []

    async def freeze_goal_display(
        self,
        loop_id: str,
        *,
        goal_id: str | None = None,
        goal_text: str,
        goal_completion: str,
        status: str = "completed",
        started_at: str | None = None,
        completed_at: str | None = None,
        duration_ms: int = 0,
        tokens_used: int = 0,
    ) -> None:
        """Fold the live ledger into an immutable goal snapshot (RFC-631)."""
        from datetime import UTC, datetime

        from soothe.backends.persistence.display_store import get_display_card_store

        try:
            state = self._buffers.get(loop_id)
            if state is not None and (state.messages or state.log_events):
                await self._flush_buffers_to_ledger(loop_id, state)
            ledger = await self.ensure_for_loop(loop_id)
            live_cards = ledger.snapshot()
            segments = split_cards_by_user_segments(live_cards)
            goal_cards = segments[-1] if segments else list(live_cards)
            store = get_display_card_store()
            now_iso = datetime.now(UTC).isoformat()
            snapshot = build_goal_snapshot(
                goal_id=goal_id or "",
                goal_index=-1,
                goal_text=goal_text,
                status=status,
                started_at=started_at or now_iso,
                completed_at=completed_at or now_iso,
                duration_ms=duration_ms,
                tokens_used=tokens_used,
                goal_completion=goal_completion,
                live_cards=goal_cards,
            )
            goal_index, resolved_goal_id = await asyncio.to_thread(
                store.insert_goal_snapshot_with_auto_index,
                loop_id,
                goal_id=goal_id,
                snapshot=snapshot.to_wire_dict(),
            )
            await ledger.reset_for_next_goal()
            if state is not None:
                state.messages.clear()
                state.log_events.clear()
            logger.info(
                "Froze goal display snapshot loop=%s goal_index=%d cards=%d",
                loop_id[:16],
                goal_index,
                snapshot.card_count,
            )
        except Exception:
            logger.warning(
                "Failed to freeze goal display snapshot for loop %s",
                loop_id,
                exc_info=True,
            )

    async def ensure_snapshots_migrated(self, loop_id: str) -> None:
        """Lazy migration: synthesize goal snapshots from legacy card ledger."""
        from soothe.backends.persistence.display_store import get_display_card_store

        store = get_display_card_store()
        if store.goal_snapshot_count(loop_id) > 0:
            return
        ledger = await self.ensure_for_loop(loop_id)
        cards = ledger.snapshot()
        if not cards:
            return
        segments = split_cards_by_user_segments(cards)
        if not segments:
            return
        from datetime import UTC, datetime

        now_iso = datetime.now(UTC).isoformat()
        for goal_index, segment in enumerate(segments):
            user_text = ""
            for card in segment:
                if card.type == MessageType.USER and card.content.strip():
                    user_text = card.content.strip()
                    break
            assistant_text = ""
            for card in reversed(segment):
                if card.type != MessageType.ASSISTANT or not card.content.strip():
                    continue
                if card.loop_output_phase == "goal_completion":
                    assistant_text = card.content.strip()
                    break
            if not assistant_text:
                for card in reversed(segment):
                    if card.type == MessageType.ASSISTANT and card.content.strip():
                        assistant_text = card.content.strip()
                        break
            goal_id = f"{loop_id}_goal_{goal_index}"
            snapshot = build_goal_snapshot(
                goal_id=goal_id,
                goal_index=goal_index,
                goal_text=user_text or f"Goal {goal_index + 1}",
                status="completed",
                started_at=now_iso,
                completed_at=now_iso,
                duration_ms=0,
                tokens_used=0,
                goal_completion=assistant_text,
                live_cards=segment,
            )
            await asyncio.to_thread(
                store.insert_goal_snapshot,
                loop_id,
                goal_index=goal_index,
                goal_id=goal_id,
                snapshot=snapshot.to_wire_dict(),
            )
        logger.info(
            "Migrated %d legacy goal snapshots for loop %s",
            len(segments),
            loop_id[:16],
        )

    async def fetch_loop_history(
        self,
        loop_id: str,
        *,
        loop_status: str | None = None,
    ) -> dict[str, Any]:
        """Return frozen goal snapshots plus the live card tail."""
        from soothe.backends.persistence.display_store import get_display_card_store
        from soothe_sdk.display.card_ledger import card_to_wire_dict

        await self.ensure_snapshots_migrated(loop_id)
        store = get_display_card_store()
        goals = [
            GoalDisplaySnapshot.from_wire_dict(raw) for raw in store.list_goal_snapshots(loop_id)
        ]
        ledger = await self.ensure_for_loop(loop_id)
        live_cards = fold_display_cards(ledger.snapshot())
        live_goal_index: int | None = None
        if live_cards and (loop_status or "").strip().lower() == "running":
            live_goal_index = len(goals)
        return {
            "loop_id": loop_id,
            "goals": [g.to_wire_dict() for g in goals],
            "live_cards": [card_to_wire_dict(c) for c in live_cards],
            "live_goal_index": live_goal_index,
            "success": True,
        }

    async def flattened_display_cards(
        self,
        loop_id: str,
        *,
        loop_status: str | None = None,
    ) -> list[Any]:
        """Flatten snapshots + live tail for ``loop_cards_fetch`` compatibility."""
        payload = await self.fetch_loop_history(loop_id, loop_status=loop_status)
        from soothe_sdk.display.card_ledger import card_from_wire_dict

        cards: list[Any] = []
        for goal_raw in payload.get("goals") or []:
            if not isinstance(goal_raw, dict):
                continue
            goal = GoalDisplaySnapshot.from_wire_dict(goal_raw)
            cards.extend(goal.display_cards)
        for raw in payload.get("live_cards") or []:
            if isinstance(raw, dict):
                cards.append(card_from_wire_dict(raw))
        return cards

    async def replay_to_client(
        self,
        loop_id: str,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> int:
        """Stream ``card.replay_begin`` → ``card.created`` × N → ``card.replay_end``."""
        ledger = await self.ensure_for_loop(loop_id)
        if ledger.card_count() == 0:
            return await self._emit_empty_replay(loop_id, send_fn)
        return await self._emit_replay_from_ledger(loop_id, ledger, send_fn)

    async def _emit_empty_replay(
        self,
        loop_id: str,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> int:
        await send_fn(
            {
                "type": CARD_REPLAY_BEGIN,
                "loop_id": loop_id,
                "total_cards": 0,
                "latest_seq": 0,
            }
        )
        await send_fn(
            {
                "type": CARD_REPLAY_END,
                "loop_id": loop_id,
                "latest_seq": 0,
                "card_count": 0,
            }
        )
        return 0

    async def _emit_replay_from_ledger(
        self,
        loop_id: str,
        ledger: LoopCardLedger,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> int:
        async with ledger.lock():
            mutations = ledger.to_mutations_snapshot()
        total = len(mutations)
        latest_seq = mutations[-1].seq if mutations else 0

        await send_fn(
            {
                "type": CARD_REPLAY_BEGIN,
                "loop_id": loop_id,
                "total_cards": total,
                "latest_seq": latest_seq,
            }
        )
        for mutation in mutations:
            await send_fn(
                {
                    "type": CARD_CREATED,
                    "loop_id": loop_id,
                    "seq": mutation.seq,
                    "card_id": mutation.card_id,
                    "kind": mutation.kind,
                    "data": mutation.data,
                }
            )
        await send_fn(
            {
                "type": CARD_REPLAY_END,
                "loop_id": loop_id,
                "latest_seq": latest_seq,
                "card_count": total,
            }
        )
        return total


__all__ = [
    "CARD_CREATED",
    "CARD_REPLAY_BEGIN",
    "CARD_REPLAY_END",
    "LoopCardManager",
    "get_card_ingest_overflow_metrics",
    "reset_card_ingest_overflow_metrics",
]
