"""Client session management for event bus architecture (RFC-0013, IG-408)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import websockets.exceptions
from soothe_sdk.core.events import STRANGE_LOOP_COMPLETED
from soothe_sdk.ux.loop_stream import is_stream_terminal_wire_dict

from soothe_daemon.bootstrap.logging import set_client_id, set_loop_id
from soothe_daemon.event import loop_event_topic
from soothe_daemon.query.stream_delivery import StreamDeliveryMode

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.events import EventMeta

    from soothe_daemon.channels.base import Channel
    from soothe_daemon.event import EventBus

logger = logging.getLogger(__name__)

_GLOBAL_TOPIC = "global"
_SENDER_FILTER_DROP_LOG_LAST: dict[str, float] = {}
_SENDER_FILTER_DROP_LOG_INTERVAL_SEC = 5.0
_HIGH_PRIORITY_SETTLE_MARGIN_S = 0.15  # IG-436: Extra settle for HIGH events
_DELIVERY_ACK_POLL_S = 0.01


def _extract_loop_id_from_wire(event: dict[str, Any]) -> str | None:
    """Return ``loop_id`` from a legacy or protocol-1 wire frame."""
    lid = event.get("loop_id")
    if isinstance(lid, str) and lid.strip():
        return lid.strip()
    if event.get("type") == "next":
        payload = event.get("payload")
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict):
                inner = data.get("loop_id")
                if isinstance(inner, str) and inner.strip():
                    return inner.strip()
    return None


def _wire_event_needs_delivery_ack(event: dict[str, Any]) -> bool:
    """True when a wire frame must be acked before turn ``complete`` / ``idle``."""
    if not isinstance(event, dict):
        return False
    etype = event.get("type", "")
    if etype == "complete":
        return True
    if etype == "event":
        mode = event.get("mode", "")
        data = event.get("data")
        if mode == "messages" and isinstance(data, (tuple, list)) and data:
            body = data[0]
            if isinstance(body, dict) and is_stream_terminal_wire_dict(body):
                return True
        if mode == "custom" and isinstance(data, dict):
            custom_type = data.get("type", "")
            if custom_type in (STRANGE_LOOP_COMPLETED, "soothe.stream.end"):
                return True
    if etype == "next":
        payload = event.get("payload")
        if isinstance(payload, dict):
            inner_mode = payload.get("mode", "")
            inner_data = payload.get("data")
            if inner_mode == "event" and isinstance(inner_data, dict):
                return _wire_event_needs_delivery_ack(inner_data)
    return False


def _delivery_tracked_units(event: dict[str, Any]) -> int:
    """Count delivery-ack units in one outbound wire frame (incl. ``event_batch``)."""
    if not isinstance(event, dict):
        return 0
    if event.get("type") == "event_batch":
        sub_events = event.get("events")
        if not isinstance(sub_events, list):
            return 0
        return sum(_delivery_tracked_units(sub) for sub in sub_events if isinstance(sub, dict))
    return 1 if _wire_event_needs_delivery_ack(event) else 0


# Wire-frame types that are already protocol-1 envelopes and must pass through
# the legacy→``next`` translator unchanged (RFC-450 §5/§9). ``status`` is a
# defined top-level protocol-1 message type (RFC-450 §9.1), so status frames
# are kept raw — only free-form streaming events become ``next`` payloads.
_PROTO1_WIRE_TYPES: frozenset[str] = frozenset(
    {
        "response",
        "error",
        "next",
        "complete",
        "connection_ack",
        "receipt_response",
        "ping",
        "pong",
        "status",
        "disconnect",
    }
)


def _to_next_envelope(event: dict[str, Any], subscription_id: str | None) -> dict[str, Any]:
    """Wrap a legacy streaming frame as a protocol-1 ``next`` envelope (RFC-450 §9.3).

    Free-form streaming frames (``event``, ``command_response``, card replay
    frames, ``status``) are translated into the unified
    ``{proto, type:"next", payload:{namespace, mode, data}, id?}`` shape. The
    original frame type becomes ``payload.mode``; ``payload.data`` carries the
    frame body (with ``loop_id`` preserved). ``status`` frames and pure
    protocol-1 frames (``response``, ``error``, ``next``, ``complete``, …) are
    returned unchanged — ``status`` is a defined top-level protocol-1 message
    type, not a subscription stream event.

    Args:
        event: Raw wire frame dict as produced by the daemon broadcast path.
        subscription_id: The subscriber's correlation id for the loop this
            frame is scoped to, or ``None`` for daemon-global frames (in which
            case the envelope ``id`` is omitted).

    Returns:
        A protocol-1 ``next`` envelope dict, or the original dict if it is
        already a protocol-1 frame or a ``status`` frame.
    """
    msg_type = event.get("type")
    if not isinstance(msg_type, str) or msg_type in _PROTO1_WIRE_TYPES:
        return event

    namespace = event.get("namespace")
    if not isinstance(namespace, list):
        namespace = []

    # Preserve the originating frame type as ``mode`` so protocol-1 consumers
    # can branch on the same discriminator the legacy clients used.
    payload: dict[str, Any] = {
        "namespace": namespace,
        "mode": msg_type,
        "data": event,
    }
    envelope: dict[str, Any] = {
        "proto": "1",
        "type": "next",
        "payload": payload,
    }
    if subscription_id:
        envelope["id"] = subscription_id
    return envelope


def _queue_has_high_priority(queue: asyncio.Queue) -> bool:
    """Peek queue to check if any HIGH/CRITICAL priority events pending (IG-436).

    Since asyncio.Queue doesn't support true peek, we temporarily drain and
    re-queue to check priorities. Only used during drain settle when queue
    has item.

    Args:
        queue: Event queue to check.

    Returns:
        True if any event has HIGH or CRITICAL priority.
    """
    if queue.empty():
        return False
    temp: list[Any] = []
    has_high = False
    from soothe.events import EventPriority

    try:
        while not queue.empty():
            item = queue.get_nowait()
            temp.append(item)
            if isinstance(item, tuple) and len(item) == 2:
                event_meta = item[1]
                if event_meta is not None and event_meta.priority.value <= EventPriority.HIGH.value:
                    has_high = True
                    # Don't need to check more - we found a HIGH event
                    break
    except asyncio.QueueEmpty:
        pass

    # Re-queue all items in order
    for item in temp:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            logger.warning("Queue full while re-queuing during priority peek")

    return has_high


@dataclass
class ClientSession:
    """Represents a connected client with loop-scoped subscriptions (IG-408).

    Attributes:
        client_id: Unique identifier for this client
        transport: Channel instance handling wire I/O
        transport_client: Channel-specific client handle (e.g. WebSocket)
        subscriptions: Set of loop_ids this client receives events for
        event_queue: Queue for delivering events to the client
        sender_task: Background task that sends events to the client
        wire_tier: Client wire filter tier (``full`` or ``progress``, IG-435)
        detach_requested: Whether client explicitly requested detach (RFC-0013)
        config: Optional SootheConfig for effective streaming config (RFC-614)
        loop_subscription_ids: Maps loop_id → subscription correlation id for ``next`` envelopes
    """

    client_id: str
    transport: Channel
    transport_client: Any  # WebSocket connection or channel-specific handle
    subscriptions: set[str] = field(default_factory=set)
    # IG-408: Bounded per-client event queue to prevent unbounded growth
    event_queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=10000)
    )
    sender_task: asyncio.Task[None] | None = None
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    wire_tier: str = "full"
    detach_requested: bool = False  # RFC-0013: client explicitly requested detach
    autopilot_subscribed: bool = False  # RFC-228: receives autopilot__* worker events
    config: SootheConfig | None = None  # RFC-614: daemon config reference
    stream_delivery: StreamDeliveryMode = "adaptive"  # IG-534 §3.2: per-client preference
    # Subscription correlation ids for protocol-1 ``next`` envelopes (RFC-450).
    loop_subscription_ids: dict[str, str] = field(default_factory=dict)  # loop_id → subscription_id


class ClientSessionManager:
    """Manages client sessions and loop-scoped subscriptions (IG-408).

    Args:
        event_bus: EventBus instance for routing events
        cancel_callback: Optional async callback to cancel work for a loop_id on disconnect.
        dispatch_cleanup_callback: Optional async callback to cleanup dispatch tasks (IG-258).
        config: Optional SootheConfig for streaming interval configuration (RFC-614).
    """

    def __init__(
        self,
        event_bus: EventBus,
        cancel_callback: Callable[[str], Coroutine[None, None, None]] | None = None,
        dispatch_cleanup_callback: Callable[[str], Coroutine[None, None, None]] | None = None,
        config: SootheConfig | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._sessions: dict[str, ClientSession] = {}
        self._lock = asyncio.Lock()
        self._client_loop_ownership: dict[str, str] = {}  # client_id → loop_id
        self._cancel_callback = cancel_callback
        self._dispatch_cleanup_callback = dispatch_cleanup_callback
        self._config = config
        # IG-556 P1.3: per-loop delivery sequence + client acks for drain gating.
        self._delivery_sent_seq: dict[tuple[str, str], int] = {}
        self._delivery_ack_seq: dict[tuple[str, str], int] = {}

    async def create_session(
        self,
        channel: Channel,
        transport_client: Any,
        client_id: str | None = None,
    ) -> str:
        """Create new client session and subscribe to daemon-wide status topic."""
        client_id = client_id or str(uuid.uuid4())

        session = ClientSession(
            client_id=client_id,
            transport=channel,
            transport_client=transport_client,
        )

        async with self._lock:
            self._sessions[client_id] = session

        await self._event_bus.subscribe(_GLOBAL_TOPIC, session.event_queue)

        await self._ensure_sender_loop(session)

        # Set client_id in logging context for full ID in daemon.log
        set_client_id(client_id)
        logger.info("[Session] Client %s connected (%s)", client_id, channel.name)

        return client_id

    def get_stream_delivery(
        self,
        *,
        client_id: str | None = None,
        loop_id: str | None = None,
    ) -> StreamDeliveryMode:
        """Return stream shaping mode for a client or loop.

        IG-534 §3.2: Preference is stored on ``ClientSession``, not a shared
        per-loop map. When ``client_id`` is provided, that session's mode wins.
        Otherwise resolve via the client that owns in-flight work on ``loop_id``.

        Args:
            client_id: Connected client whose preference to read.
            loop_id: Loop used to find the owning client when ``client_id`` is omitted.

        Returns:
            ``batch`` | ``adaptive`` | ``streaming`` (defaults to ``adaptive``).
        """
        if client_id:
            session = self._sessions.get(client_id)
            if session is not None:
                return session.stream_delivery
        if loop_id:
            for owner_id, owned_loop in self._client_loop_ownership.items():
                if owned_loop == loop_id:
                    session = self._sessions.get(owner_id)
                    if session is not None:
                        return session.stream_delivery
        return "adaptive"

    async def subscribe_loop(
        self,
        client_id: str,
        loop_id: str,
        *,
        stream_delivery: StreamDeliveryMode | None = None,
        wire_tier: str = "full",
        subscription_id: str | None = None,  # correlation id for protocol-1 ``next`` envelopes
    ) -> bool:
        """Subscribe client to loop event topic; replaces prior loop subscriptions.

        For strict isolation, also unsubscribes from the ``global`` topic when
        subscribing to a specific loop. Loop-scoped clients should only receive
        events from their subscribed loop, not daemon-wide broadcasts.

        RFC-222 §WorkerPool: refuses subscriptions to ``autopilot__*`` worker
        loop_ids. Those are internal autopilot subprocess workers and must
        never be exposed as user-facing sessions.

        RFC-228: If client has ``autopilot_subscribed=True``, bypass the
        worker filter so subscribed clients can observe autopilot assignment
        loops (``subscribe_thread`` on ``autopilot__*`` ids).
        """
        try:
            from soothe.autopilot.worker_pool import is_autopilot_worker_loop_id

            if is_autopilot_worker_loop_id(loop_id):
                # RFC-228: Check if client has autopilot subscription bypass
                async with self._lock:
                    session = self._sessions.get(client_id)
                if session is None or not session.autopilot_subscribed:
                    logger.warning(
                        "[Session] rejected subscribe to autopilot worker loop %s by client %s "
                        "(autopilot_subscribe required per RFC-228)",
                        loop_id,
                        client_id,
                    )
                    return False
                # Client has autopilot_subscribed=True, allow subscription
                logger.info(
                    "[Session] allowing autopilot worker subscription %s for client %s (RFC-228 bypass)",
                    loop_id,
                    client_id,
                )
        except Exception:
            # Helper unavailable — fall through; this is purely a defensive gate.
            logger.debug("autopilot worker loop_id check unavailable", exc_info=True)

        async with self._lock:
            session = self._sessions.get(client_id)

        if not session:
            logger.warning(
                "[Session] Client %s not found for loop subscription %s (likely disconnected)",
                client_id,
                loop_id,
            )
            return False

        session.wire_tier = wire_tier if wire_tier in ("full", "progress") else "full"
        if stream_delivery is not None:
            # IG-441: accept the canonical three modes (batch / adaptive / streaming).
            # Unknown values fall back to "batch" for safety.
            delivery: StreamDeliveryMode = (
                stream_delivery
                if stream_delivery in ("batch", "adaptive", "streaming")
                else "batch"
            )
            session.stream_delivery = delivery
        else:
            delivery = session.stream_delivery

        # Strict single-loop subscription per client for isolation
        for prev in list(session.subscriptions):
            if prev != loop_id:
                await self._event_bus.unsubscribe(loop_event_topic(prev), session.event_queue)
                session.subscriptions.discard(prev)

        topic = loop_event_topic(loop_id)
        await self._event_bus.subscribe(topic, session.event_queue)
        session.subscriptions.add(loop_id)
        # Store subscription_id for correlating ``next`` envelopes.
        if subscription_id is not None:
            session.loop_subscription_ids[loop_id] = subscription_id

        # Unsubscribe from global for strict loop isolation (IG-408)
        # Loop-scoped clients should only receive events from their subscribed loop
        await self._event_bus.unsubscribe(_GLOBAL_TOPIC, session.event_queue)

        logger.info(
            "[Session] Client %s → loop %s (stream_delivery=%s, wire_tier=%s)",
            client_id,
            loop_id,
            delivery,
            session.wire_tier,
        )
        await self._ensure_sender_loop(session)
        return True

    async def unsubscribe_loop(self, client_id: str, loop_id: str) -> bool:
        """Unsubscribe client from a loop topic."""
        async with self._lock:
            session = self._sessions.get(client_id)

        if not session:
            logger.debug(
                "[Session] Client %s not found for loop unsubscription %s",
                client_id,
                loop_id,
            )
            return False

        topic = loop_event_topic(loop_id)
        await self._event_bus.unsubscribe(topic, session.event_queue)
        session.subscriptions.discard(loop_id)
        # Drop subscription_id tracking for this loop.
        session.loop_subscription_ids.pop(loop_id, None)

        # Set logging context for full IDs
        set_client_id(client_id)
        set_loop_id(loop_id)
        logger.info("[Session] Client %s ← loop %s", client_id, loop_id)
        return True

    async def remove_session(self, client_id: str) -> None:
        """Remove client session and cleanup."""
        # Set logging context for full client_id in daemon.log
        set_client_id(client_id)

        async with self._lock:
            session = self._sessions.pop(client_id, None)
            owned_loop_id = self._client_loop_ownership.pop(client_id, None)

        if not session:
            return

        self._clear_client_delivery_state(client_id, session)

        # Set loop_id context when client owns a loop
        if owned_loop_id:
            set_loop_id(owned_loop_id)

        if not session.detach_requested and owned_loop_id:
            if self._cancel_callback:
                try:
                    await self._cancel_callback(owned_loop_id)
                    logger.info(
                        "[Session] Loop %s cancelled (client %s disconnect)",
                        owned_loop_id,
                        client_id,
                    )
                except Exception:
                    logger.exception(
                        "Failed to cancel loop %s on client %s disconnect",
                        owned_loop_id,
                        client_id,
                    )
            else:
                logger.debug(
                    "No cancel_callback set, skipping auto-cancel for loop %s",
                    owned_loop_id,
                )

        if self._dispatch_cleanup_callback:
            try:
                await self._dispatch_cleanup_callback(client_id)
                logger.debug("[Session] Dispatch tasks cancelled for client %s", client_id)
            except Exception:
                logger.exception(
                    "Failed to cleanup dispatch tasks for client %s",
                    client_id,
                )

        if session.sender_task:
            session.sender_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session.sender_task

        await self._event_bus.unsubscribe_all(session.event_queue)

        logger.info("[Session] Client %s disconnected", client_id)

    async def get_session(self, client_id: str) -> ClientSession | None:
        """Get session by client_id."""
        async with self._lock:
            return self._sessions.get(client_id)

    async def claim_loop_ownership(self, client_id: str, loop_id: str) -> None:
        """Record that this client owns in-flight work for the loop."""
        # Set logging context for full IDs in daemon.log
        set_client_id(client_id)
        set_loop_id(loop_id)
        async with self._lock:
            self._client_loop_ownership[client_id] = loop_id
            session = self._sessions.get(client_id)
            logger.debug("Client %s claimed ownership of loop %s", client_id, loop_id)
        if session is not None:
            await self._ensure_sender_loop(session)

    async def release_loop_ownership(self, client_id: str) -> str | None:
        """Release loop ownership; returns the loop_id if any.

        IG-490: Wait for queue drain when sender is alive to prevent race condition
        where events arrive after await_loop_delivery_drained() but before ownership
        release (e.g., "idle" status broadcast after goal completion).
        """
        # Set logging context for full client_id in daemon.log
        set_client_id(client_id)
        loop_id: str | None = None
        async with self._lock:
            loop_id = self._client_loop_ownership.pop(client_id, None)
        if loop_id:
            # Set logging context for full loop_id in daemon.log
            set_loop_id(loop_id)
            session = self._sessions.get(client_id)
            if session is not None:
                backlog = session.event_queue.qsize()
                sender_alive = session.sender_task is not None and not session.sender_task.done()
                if backlog > 0 and sender_alive:
                    # IG-490: Wait for sender to drain events before releasing
                    # This prevents race where idle status arrives after drain check
                    logger.debug(
                        "Client %s has %d undelivered event(s) with sender alive, "
                        "waiting for drain (loop=%s)",
                        client_id,
                        backlog,
                        loop_id,
                    )
                    # Wait up to 500ms for queue to drain
                    drain_start = time.monotonic()
                    max_drain_wait = 0.5
                    while (
                        session.event_queue.qsize() > 0
                        and time.monotonic() - drain_start < max_drain_wait
                        and session.sender_task is not None
                        and not session.sender_task.done()
                    ):
                        await asyncio.sleep(0.05)
                    remaining = session.event_queue.qsize()
                    if remaining > 0:
                        logger.warning(
                            "Client %s still has %d undelivered event(s) after drain wait "
                            "(sender_alive=%s, loop=%s)",
                            client_id,
                            remaining,
                            not session.sender_task.done() if session.sender_task else False,
                            loop_id,
                        )
                elif backlog > 0:
                    logger.warning(
                        "Client %s has %d undelivered event(s) in session queue "
                        "(sender_alive=%s, loop=%s)",
                        client_id,
                        backlog,
                        sender_alive,
                        loop_id,
                    )
                    if not sender_alive:
                        await self._ensure_sender_loop(session)
            logger.debug("Client %s released ownership of loop %s", client_id, loop_id)
        return loop_id

    async def get_owned_loop(self, client_id: str) -> str | None:
        """Return loop_id owned by client without releasing."""
        async with self._lock:
            return self._client_loop_ownership.get(client_id)

    def _clear_client_delivery_state(self, client_id: str, session: ClientSession) -> None:
        """Drop delivery-ack counters for one disconnected client."""
        for loop_id in list(session.subscriptions):
            self._delivery_sent_seq.pop((loop_id, client_id), None)
            self._delivery_ack_seq.pop((loop_id, client_id), None)

    def note_delivery_sent(self, loop_id: str, client_id: str, *, units: int = 1) -> int:
        """Increment outbound delivery sequence for a loop/client pair."""
        if units <= 0:
            key = (loop_id, client_id)
            return self._delivery_sent_seq.get(key, 0)
        key = (loop_id, client_id)
        seq = self._delivery_sent_seq.get(key, 0) + units
        self._delivery_sent_seq[key] = seq
        return seq

    def record_delivery_ack(self, client_id: str, loop_id: str, seq: int) -> None:
        """Record the highest delivery sequence acked by a client."""
        if seq <= 0:
            return
        key = (loop_id, client_id)
        prev = self._delivery_ack_seq.get(key, 0)
        if seq > prev:
            self._delivery_ack_seq[key] = seq

    def _delivery_boundary_for_loop(self, loop_id: str) -> int:
        """Return max outbound delivery seq across subscribers for ``loop_id``."""
        boundary = 0
        for session in self._sessions.values():
            if loop_id not in session.subscriptions:
                continue
            boundary = max(
                boundary,
                self._delivery_sent_seq.get((loop_id, session.client_id), 0),
            )
        return boundary

    def _delivery_acks_met(self, loop_id: str, boundary: int) -> bool:
        """True when every subscribed client has acked through ``boundary``."""
        if boundary <= 0:
            return True
        for session in self._sessions.values():
            if loop_id not in session.subscriptions:
                continue
            acked = self._delivery_ack_seq.get((loop_id, session.client_id), 0)
            if acked < boundary:
                return False
        return True

    def _note_delivery_sent_for_events(self, client_id: str, events: list[dict[str, Any]]) -> None:
        """Bump delivery seq for each tracked unit in outbound frames."""
        for event in events:
            units = _delivery_tracked_units(event)
            if units <= 0:
                continue
            loop_id = _extract_loop_id_from_wire(event)
            if loop_id:
                self.note_delivery_sent(loop_id, client_id, units=units)
                continue
            if event.get("type") == "event_batch":
                sub_events = event.get("events")
                if not isinstance(sub_events, list):
                    continue
                for sub in sub_events:
                    if isinstance(sub, dict) and _wire_event_needs_delivery_ack(sub):
                        sub_loop = _extract_loop_id_from_wire(sub)
                        if sub_loop:
                            self.note_delivery_sent(sub_loop, client_id)

    async def send_to_client(self, session: ClientSession, message: dict[str, Any]) -> None:
        """Send a wire message to one client (serialized per WebSocket connection).

        Legacy streaming frames are translated to protocol-1 ``next`` envelopes
        at this boundary (RFC-450 §9.3) so every client receives the unified
        wire shape regardless of which daemon code path produced the frame.
        """
        wire = self._translate_for_client(session, message)
        async with session.send_lock:
            await session.transport.send(session.transport_client, wire)
        self._note_delivery_sent_for_events(session.client_id, [message])

    def _translate_for_client(
        self, session: ClientSession, message: dict[str, Any]
    ) -> dict[str, Any]:
        """Translate a legacy frame to a protocol-1 envelope for this session.

        ``event_batch`` wrappers are preserved as a transport-level optimization;
        each sub-event is individually wrapped as a ``next`` envelope. The SDK
        client expands ``event_batch`` on receive, so downstream ``next()``
        readers see one ``next`` payload per sub-event.
        """
        if not isinstance(message, dict):
            return message
        if message.get("type") == "event_batch":
            sub_events = message.get("events")
            if isinstance(sub_events, list):
                wrapped: list[dict[str, Any]] = []
                for sub in sub_events:
                    if isinstance(sub, dict):
                        wrapped.append(
                            _to_next_envelope(sub, self._subscription_id_for(session, sub))
                        )
                    else:
                        wrapped.append(sub)  # type: ignore[arg-type]
                return {"type": "event_batch", "events": wrapped}
            return message
        return _to_next_envelope(message, self._subscription_id_for(session, message))

    @staticmethod
    def _subscription_id_for(session: ClientSession, message: dict[str, Any]) -> str | None:
        """Return this session's subscription id for the frame's loop, if any."""
        lid = str(message.get("loop_id") or "").strip()
        if not lid:
            return None
        sub_id = session.loop_subscription_ids.get(lid)
        return sub_id if isinstance(sub_id, str) and sub_id else None

    async def wake_senders_for_loop(self, loop_id: str) -> None:
        """Ensure sender tasks are running for clients subscribed to a loop."""
        async with self._lock:
            sessions = [
                session for session in self._sessions.values() if loop_id in session.subscriptions
            ]
        for session in sessions:
            await self._ensure_sender_loop(session)

    def _log_sender_task_outcome(self, session: ClientSession, task: asyncio.Task[None]) -> None:
        """Log unexpected sender task termination (helps debug silent hangs)."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            set_client_id(session.client_id)
            logger.warning(
                "Sender loop exited for client %s: %s: %s",
                session.client_id,
                type(exc).__name__,
                exc,
                exc_info=exc,
            )

    async def _ensure_sender_loop(self, session: ClientSession) -> None:
        """Start or restart the background sender when it is missing or dead."""
        task = session.sender_task
        if task is not None and not task.done():
            return
        if task is not None:
            self._log_sender_task_outcome(session, task)
        set_client_id(session.client_id)
        session.sender_task = asyncio.create_task(self._sender_loop(session))
        session.sender_task.add_done_callback(
            lambda completed: self._log_sender_task_outcome(session, completed)
        )

    async def _sender_loop(self, session: ClientSession) -> None:
        """Send events from queue with daemon-side filtering and batching (RFC-0022, IG-258).

        IG-436: HIGH/CRITICAL priority events flush immediately without batch wait.
        This prevents goal_completion events from being delayed by the batch timeout.
        """
        # Set logging context for full client_id in daemon.log
        set_client_id(session.client_id)
        logger.debug("Sender loop started for client %s", session.client_id)
        batch_timeout = self._get_batch_timeout()

        try:
            batch: list[dict[str, Any]] = []
            while True:
                try:
                    skip_batch_fill = False  # IG-436: Flag for HIGH priority flush
                    try:
                        event_data = await asyncio.wait_for(
                            session.event_queue.get(), timeout=batch_timeout
                        )
                        batch.append(event_data)

                        # IG-436: Check priority - flush HIGH/CRITICAL immediately
                        if isinstance(event_data, tuple) and len(event_data) == 2:
                            event_meta = event_data[1]
                            if event_meta is not None:
                                from soothe.events import EventPriority

                                if event_meta.priority.value <= EventPriority.HIGH.value:
                                    skip_batch_fill = True
                                    logger.debug(
                                        "Client %s received HIGH priority event, "
                                        "flushing immediately (priority=%s)",
                                        session.client_id,
                                        event_meta.priority.name,
                                    )
                    except TimeoutError:
                        if not batch:
                            continue

                    # IG-436: Skip batch fill for HIGH priority events
                    if not skip_batch_fill:
                        while not session.event_queue.empty() and len(batch) < 50:
                            try:
                                event_data = session.event_queue.get_nowait()
                                batch.append(event_data)
                            except asyncio.QueueEmpty:
                                break

                    filtered_events: list[dict[str, Any]] = []
                    for event_data in batch:
                        event: dict[str, Any]
                        event_meta: EventMeta | None = None

                        if isinstance(event_data, tuple):
                            if len(event_data) != 2:
                                logger.warning(
                                    "Client %s sender skipping malformed queue item "
                                    "(expected 2-tuple, got %d)",
                                    session.client_id,
                                    len(event_data),
                                )
                                continue
                            event, event_meta = event_data
                        else:
                            event = event_data

                        from soothe.events.visibility import (
                            decide_client_wire_visibility,
                            is_progress_wire_event,
                        )

                        if not isinstance(event, dict):
                            continue

                        decision = decide_client_wire_visibility(event, event_meta=event_meta)
                        if not decision.visible:
                            # Defense in depth: broadcast layer already filtered.
                            # Re-classification here catches direct queue.put_nowait
                            # callers that bypass _broadcast (history replay, etc.).
                            logger.debug(
                                "Client %s sender suppressing event (kind=%s, reason=%s)",
                                session.client_id,
                                decision.kind.value,
                                decision.reason,
                            )
                            continue
                        if session.wire_tier == "progress" and not is_progress_wire_event(event):
                            continue

                        filtered_events.append(event)

                    dropped_batch_size = len(batch)
                    batch.clear()
                    if not filtered_events:
                        from soothe_daemon.event.bus import _throttle_log

                        if _throttle_log(
                            _SENDER_FILTER_DROP_LOG_LAST,
                            session.client_id,
                            interval=_SENDER_FILTER_DROP_LOG_INTERVAL_SEC,
                        ):
                            logger.warning(
                                "Client %s sender dropped a batch of %d event(s) after "
                                "daemon-side filtering (wire_tier=%s)",
                                session.client_id,
                                dropped_batch_size,
                                session.wire_tier,
                            )
                        continue

                    if len(filtered_events) > 1:
                        await self.send_to_client(
                            session,
                            {"type": "event_batch", "events": filtered_events},
                        )
                    else:
                        await self.send_to_client(session, filtered_events[0])
                except websockets.exceptions.ConnectionClosedOK:
                    logger.warning(
                        "Client %s sender stopped: disconnected normally while sending (%d queued)",
                        session.client_id,
                        session.event_queue.qsize(),
                    )
                    break
                except websockets.exceptions.ConnectionClosedError:
                    logger.warning(
                        "Client %s sender stopped: disconnected abnormally while sending "
                        "(%d queued)",
                        session.client_id,
                        session.event_queue.qsize(),
                    )
                    break
                except ConnectionError as e:
                    logger.warning(
                        "Client %s sender stopped while sending (%d queued): %s",
                        session.client_id,
                        session.event_queue.qsize(),
                        e,
                    )
                    break
                except Exception:
                    logger.warning(
                        "Client %s sender loop error (%d queued), stopping sender",
                        session.client_id,
                        session.event_queue.qsize(),
                        exc_info=True,
                    )
                    break

        except asyncio.CancelledError:
            # Set logging context for full client_id in daemon.log
            set_client_id(session.client_id)
            logger.debug("Sender task cancelled for client %s", session.client_id)
            raise

    def _get_batch_timeout(self) -> float:
        """Get batch timeout from config (RFC-614).

        Returns:
            Timeout in seconds (default 0.2 = 200ms).
        """
        if self._config is None:
            return 0.2  # 200ms default
        streaming_cfg = self._config.agent.loop.output_streaming
        return streaming_cfg.streaming_interval_ms / 1000.0

    async def await_loop_delivery_drained(
        self,
        loop_id: str,
        *,
        batch_timeout_s: float | None = None,
        max_wait_s: float = 30.0,
        require_delivery_acks: bool = True,
    ) -> bool:
        """Wait until subscribed session queues are empty and sender batch window elapses.

        Ensures ``goal_completion`` and other tail frames are flushed before ``status: idle``.

        IG-436: Adds extra settle margin for HIGH/CRITICAL priority events to prevent
        race condition where sender hasn't flushed batched goal_completion before
        ownership release.

        IG-556 P1.3: After queue drain, waits until clients ack outbound delivery
        sequence through terminal frames (or times out with a degraded warning).

        Args:
            loop_id: Loop scope to drain.
            batch_timeout_s: Sender/coalesce flush window; defaults to config interval.
            max_wait_s: Hard cap on wait time.
            require_delivery_acks: When False, skip client ack gating (tests).

        Returns:
            True if queues stayed empty after the flush window, False on timeout.
        """
        import time

        flush_s = batch_timeout_s if batch_timeout_s is not None else self._get_batch_timeout()
        settle_s = max(flush_s, 0.05) + 0.05
        started = time.monotonic()
        deadline = started + max_wait_s
        queues_drained = False

        while time.monotonic() < deadline:
            async with self._lock:
                queues = [
                    session.event_queue
                    for session in self._sessions.values()
                    if loop_id in session.subscriptions
                ]
            if not queues:
                queues_drained = True
                break
            if any(q.qsize() > 0 for q in queues):
                await asyncio.sleep(0.05)
                continue
            await asyncio.sleep(settle_s)
            async with self._lock:
                queues = [
                    session.event_queue
                    for session in self._sessions.values()
                    if loop_id in session.subscriptions
                ]
            if queues and all(q.empty() for q in queues):
                queues_drained = True
                break
            # IG-436: Check for HIGH priority events that arrived during settle
            if queues and any(_queue_has_high_priority(q) for q in queues):
                logger.debug(
                    "Loop %s drain: HIGH priority event(s) pending, adding extra settle margin",
                    loop_id[:16],
                )
                await asyncio.sleep(_HIGH_PRIORITY_SETTLE_MARGIN_S)
                # Re-check after extra margin
                async with self._lock:
                    queues = [
                        session.event_queue
                        for session in self._sessions.values()
                        if loop_id in session.subscriptions
                    ]
                if queues and all(q.empty() for q in queues):
                    queues_drained = True
                    break
            await asyncio.sleep(0.05)

        if not queues_drained:
            logger.warning(
                "Loop %s delivery drain timed out after %.1fs (queues may still hold events)",
                loop_id[:16],
                max_wait_s,
            )
            return False

        if not require_delivery_acks:
            return True

        boundary = self._delivery_boundary_for_loop(loop_id)
        if boundary <= 0:
            return True

        while time.monotonic() < deadline:
            if self._delivery_acks_met(loop_id, boundary):
                return True
            await asyncio.sleep(_DELIVERY_ACK_POLL_S)

        logger.warning(
            "Loop %s delivery ack drain degraded: boundary=%d not acked by all clients",
            loop_id[:16],
            boundary,
        )
        return False

    @property
    def session_count(self) -> int:
        """Return number of active sessions."""
        return len(self._sessions)
