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
from soothe_sdk.core.types import VerbosityLevel

from soothe_daemon.event import loop_event_topic
from soothe_daemon.logging import set_client_id, set_loop_id
from soothe_daemon.query.stream_delivery import StreamDeliveryMode

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.config.models import OutputStreamingConfig
    from soothe.core.events import EventMeta

    from soothe_daemon.event import EventBus
    from soothe_daemon.transports.base import TransportServer

logger = logging.getLogger(__name__)

_GLOBAL_TOPIC = "global"
_SENDER_FILTER_DROP_LOG_LAST: dict[str, float] = {}
_SENDER_FILTER_DROP_LOG_INTERVAL_SEC = 5.0
_HIGH_PRIORITY_SETTLE_MARGIN_S = 0.15  # IG-436: Extra settle for HIGH events


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
    from soothe.core.events import EventPriority

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
        transport: Transport server instance
        transport_client: Transport-specific client object
        subscriptions: Set of loop_ids this client receives events for
        event_queue: Queue for delivering events to the client
        sender_task: Background task that sends events to the client
        verbosity: Client verbosity preference (RFC-0022)
        wire_tier: Client wire filter tier (``full`` or ``progress``, IG-435)
        detach_requested: Whether client explicitly requested detach (RFC-0013)
        config: Optional SootheConfig for effective streaming config (RFC-614)
    """

    client_id: str
    transport: TransportServer
    transport_client: Any  # Transport-specific client object
    subscriptions: set[str] = field(default_factory=set)
    event_queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=10000)
    )
    sender_task: asyncio.Task[None] | None = None
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    verbosity: VerbosityLevel = "normal"  # RFC-0022: client verbosity preference
    wire_tier: str = "full"
    detach_requested: bool = False  # RFC-0013: client explicitly requested detach
    config: SootheConfig | None = None  # RFC-614: daemon config reference

    def get_effective_streaming_config(
        self, cli_overrides: dict[str, Any] | None = None
    ) -> OutputStreamingConfig:
        """Get effective streaming config with CLI overrides (RFC-614).

        Args:
            cli_overrides: Optional dict with output_streaming_enabled, output_streaming_mode

        Returns:
            Effective OutputStreamingConfig with overrides applied.
        """
        if self.config is None:
            # Return defaults if no config
            from soothe.config.models import OutputStreamingConfig

            return OutputStreamingConfig()

        config = self.config.agent.loop.output_streaming

        if cli_overrides:
            # Apply CLI overrides (per-session override)
            if cli_overrides.get("output_streaming_enabled") is not None:
                config.enabled = cli_overrides["output_streaming_enabled"]
            if cli_overrides.get("output_streaming_mode") is not None:
                config.mode = cli_overrides["output_streaming_mode"]

        return config


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
        self._loop_stream_delivery: dict[str, StreamDeliveryMode] = {}
        self._cancel_callback = cancel_callback
        self._dispatch_cleanup_callback = dispatch_cleanup_callback
        self._config = config

    async def create_session(
        self,
        transport: TransportServer,
        transport_client: Any,
        client_id: str | None = None,
    ) -> str:
        """Create new client session and subscribe to daemon-wide status topic."""
        client_id = client_id or str(uuid.uuid4())

        session = ClientSession(
            client_id=client_id,
            transport=transport,
            transport_client=transport_client,
        )

        async with self._lock:
            self._sessions[client_id] = session

        await self._event_bus.subscribe(_GLOBAL_TOPIC, session.event_queue)

        await self._ensure_sender_loop(session)

        # Set client_id in logging context for full ID in daemon.log
        set_client_id(client_id)
        logger.info("[Session] Client %s connected (%s)", client_id, transport.transport_type)

        return client_id

    def get_stream_delivery(self, loop_id: str) -> StreamDeliveryMode:
        """Return stream shaping mode for a loop (``batch`` or ``adaptive``)."""
        return self._loop_stream_delivery.get(loop_id, "batch")

    async def subscribe_loop(
        self,
        client_id: str,
        loop_id: str,
        verbosity: VerbosityLevel = "normal",
        *,
        stream_delivery: StreamDeliveryMode | None = None,
        wire_tier: str = "full",
    ) -> bool:
        """Subscribe client to loop event topic; replaces prior loop subscriptions.

        For strict isolation, also unsubscribes from the ``global`` topic when
        subscribing to a specific loop. Loop-scoped clients should only receive
        events from their subscribed loop, not daemon-wide broadcasts.
        """
        async with self._lock:
            session = self._sessions.get(client_id)

        if not session:
            logger.warning(
                "[Session] Client %s not found for loop subscription %s (likely disconnected)",
                client_id,
                loop_id,
            )
            return False

        session.verbosity = verbosity
        session.wire_tier = wire_tier if wire_tier in ("full", "progress") else "full"
        if stream_delivery is not None:
            # Accept "streaming" for backwards compatibility, map to "adaptive"
            delivery: StreamDeliveryMode = (
                stream_delivery if stream_delivery in ("batch", "adaptive") else "batch"
            )
            self._loop_stream_delivery[loop_id] = delivery
        else:
            delivery = self._loop_stream_delivery.get(loop_id, "batch")

        # Strict single-loop subscription per client for isolation
        for prev in list(session.subscriptions):
            if prev != loop_id:
                await self._event_bus.unsubscribe(loop_event_topic(prev), session.event_queue)
                session.subscriptions.discard(prev)

        topic = loop_event_topic(loop_id)
        await self._event_bus.subscribe(topic, session.event_queue)
        session.subscriptions.add(loop_id)

        # Unsubscribe from global for strict loop isolation (IG-408)
        # Loop-scoped clients should only receive events from their subscribed loop
        await self._event_bus.unsubscribe(_GLOBAL_TOPIC, session.event_queue)

        logger.info(
            "[Session] Client %s → loop %s (verbosity=%s, stream_delivery=%s, wire_tier=%s)",
            client_id,
            loop_id,
            verbosity,
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

        IG-XXX: Wait for queue drain when sender is alive to prevent race condition
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
                    # IG-XXX: Wait for sender to drain events before releasing
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

    async def send_to_client(self, session: ClientSession, message: dict[str, Any]) -> None:
        """Send a wire message to one client (serialized per WebSocket connection)."""
        async with session.send_lock:
            await session.transport.send(session.transport_client, message)

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
                                from soothe.core.events import EventPriority

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

                        from soothe.core.events.visibility import (
                            is_client_wire_visible,
                            is_progress_wire_event,
                        )

                        if not isinstance(event, dict):
                            continue

                        if not is_client_wire_visible(event, event_meta=event_meta):
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
                                "daemon-side filtering (verbosity=%s, wire_tier=%s)",
                                session.client_id,
                                dropped_batch_size,
                                session.verbosity,
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
    ) -> bool:
        """Wait until subscribed session queues are empty and sender batch window elapses.

        Ensures ``goal_completion`` and other tail frames are flushed before ``status: idle``.

        IG-436: Adds extra settle margin for HIGH/CRITICAL priority events to prevent
        race condition where sender hasn't flushed batched goal_completion before
        ownership release.

        Args:
            loop_id: Loop scope to drain.
            batch_timeout_s: Sender/coalesce flush window; defaults to config interval.
            max_wait_s: Hard cap on wait time.

        Returns:
            True if queues stayed empty after the flush window, False on timeout.
        """
        import time

        flush_s = batch_timeout_s if batch_timeout_s is not None else self._get_batch_timeout()
        settle_s = max(flush_s, 0.05) + 0.05
        deadline = time.monotonic() + max_wait_s

        while time.monotonic() < deadline:
            async with self._lock:
                queues = [
                    session.event_queue
                    for session in self._sessions.values()
                    if loop_id in session.subscriptions
                ]
            if not queues:
                return True
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
                return True
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
                    return True
            await asyncio.sleep(0.05)
        logger.warning(
            "Loop %s delivery drain timed out after %.1fs (queues may still hold events)",
            loop_id[:16],
            max_wait_s,
        )
        return False

    @property
    def session_count(self) -> int:
        """Return number of active sessions."""
        return len(self._sessions)
