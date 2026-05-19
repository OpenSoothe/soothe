"""Client session management for event bus architecture (RFC-0013, IG-408)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import websockets.exceptions
from soothe_sdk.core.types import VerbosityLevel

from soothe_daemon.event import loop_event_topic
from soothe_daemon.query.stream_delivery import StreamDeliveryMode

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.config.models import OutputStreamingConfig
    from soothe.core.events import EventMeta

    from soothe_daemon.event import EventBus
    from soothe_daemon.transports.base import TransportServer

logger = logging.getLogger(__name__)

_GLOBAL_TOPIC = "global"


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
    verbosity: VerbosityLevel = "normal"  # RFC-0022: client verbosity preference
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

        config = self.config.output_streaming

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
    """

    def __init__(
        self,
        event_bus: EventBus,
        cancel_callback: Callable[[str], Coroutine[None, None, None]] | None = None,
        dispatch_cleanup_callback: Callable[[str], Coroutine[None, None, None]] | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._sessions: dict[str, ClientSession] = {}
        self._lock = asyncio.Lock()
        self._client_loop_ownership: dict[str, str] = {}  # client_id → loop_id
        self._loop_stream_delivery: dict[str, StreamDeliveryMode] = {}
        self._cancel_callback = cancel_callback
        self._dispatch_cleanup_callback = dispatch_cleanup_callback

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

        # Start sender task
        session.sender_task = asyncio.create_task(self._sender_loop(session))

        logger.info("[Session] Client %s connected (%s)", client_id[:8], transport.transport_type)

        return client_id

    def get_stream_delivery(self, loop_id: str) -> StreamDeliveryMode:
        """Return stream shaping mode for a loop (``batch`` or ``streaming``)."""
        return self._loop_stream_delivery.get(loop_id, "batch")

    async def subscribe_loop(
        self,
        client_id: str,
        loop_id: str,
        verbosity: VerbosityLevel = "normal",
        *,
        stream_delivery: StreamDeliveryMode = "batch",
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
                client_id[:8],
                loop_id[:8],
            )
            return False

        session.verbosity = verbosity
        delivery: StreamDeliveryMode = (
            stream_delivery if stream_delivery in ("batch", "streaming") else "batch"
        )
        self._loop_stream_delivery[loop_id] = delivery

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
            "[Session] Client %s → loop %s (verbosity=%s, stream_delivery=%s)",
            client_id[:8],
            loop_id[:8],
            verbosity,
            delivery,
        )
        return True

    async def unsubscribe_loop(self, client_id: str, loop_id: str) -> bool:
        """Unsubscribe client from a loop topic."""
        async with self._lock:
            session = self._sessions.get(client_id)

        if not session:
            logger.debug(
                "[Session] Client %s not found for loop unsubscription %s",
                client_id[:8],
                loop_id[:8],
            )
            return False

        topic = loop_event_topic(loop_id)
        await self._event_bus.unsubscribe(topic, session.event_queue)
        session.subscriptions.discard(loop_id)

        logger.info("[Session] Client %s ← loop %s", client_id[:8], loop_id[:8])
        return True

    async def remove_session(self, client_id: str) -> None:
        """Remove client session and cleanup."""
        async with self._lock:
            session = self._sessions.pop(client_id, None)
            owned_loop_id = self._client_loop_ownership.pop(client_id, None)

        if not session:
            return

        if not session.detach_requested and owned_loop_id:
            if self._cancel_callback:
                try:
                    await self._cancel_callback(owned_loop_id)
                    logger.info(
                        "[Session] Loop %s cancelled (client %s disconnect)",
                        owned_loop_id[:8],
                        client_id[:8],
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
                logger.debug("[Session] Dispatch tasks cancelled for client %s", client_id[:8])
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

        logger.info("[Session] Client %s disconnected", client_id[:8])

    async def get_session(self, client_id: str) -> ClientSession | None:
        """Get session by client_id."""
        async with self._lock:
            return self._sessions.get(client_id)

    async def claim_loop_ownership(self, client_id: str, loop_id: str) -> None:
        """Record that this client owns in-flight work for the loop."""
        async with self._lock:
            self._client_loop_ownership[client_id] = loop_id
            logger.debug("Client %s claimed ownership of loop %s", client_id, loop_id)

    async def release_loop_ownership(self, client_id: str) -> str | None:
        """Release loop ownership; returns the loop_id if any."""
        async with self._lock:
            loop_id = self._client_loop_ownership.pop(client_id, None)
            if loop_id:
                logger.debug("Client %s released ownership of loop %s", client_id, loop_id)
            return loop_id

    async def get_owned_loop(self, client_id: str) -> str | None:
        """Return loop_id owned by client without releasing."""
        async with self._lock:
            return self._client_loop_ownership.get(client_id)

    async def _sender_loop(self, session: ClientSession) -> None:
        """Send events from queue with daemon-side filtering and batching (RFC-0022, IG-258)."""
        logger.debug("Sender loop started for client %s", session.client_id[:8])
        batch_timeout = 0.05  # 50ms batch window (IG-258)

        try:
            batch: list[dict[str, Any]] = []
            while True:
                try:
                    event_data = await asyncio.wait_for(
                        session.event_queue.get(), timeout=batch_timeout
                    )
                    batch.append(event_data)
                except TimeoutError:
                    if not batch:
                        continue

                while not session.event_queue.empty() and len(batch) < 10:
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
                        event, event_meta = event_data
                    else:
                        event = event_data

                    if event_meta:
                        is_heartbeat = False
                        if isinstance(event, dict) and event.get("type") == "event":
                            ev_data = event.get("data")
                            if isinstance(ev_data, dict):
                                is_heartbeat = (
                                    ev_data.get("type") == "soothe.system.daemon.heartbeat"
                                )

                        if not is_heartbeat:
                            from soothe_sdk.core.verbosity import should_show

                            if not should_show(event_meta.verbosity, session.verbosity):
                                continue

                    filtered_events.append(event)

                batch.clear()
                if not filtered_events:
                    continue

                try:
                    for event in filtered_events:
                        await session.transport.send(session.transport_client, event)
                except websockets.exceptions.ConnectionClosedOK:
                    logger.debug(
                        "Client %s disconnected normally while sending",
                        session.client_id[:8],
                    )
                    break
                except websockets.exceptions.ConnectionClosedError:
                    logger.debug(
                        "Client %s disconnected abnormally while sending",
                        session.client_id[:8],
                    )
                    break
                except ConnectionError as e:
                    logger.debug(
                        "Client %s disconnected while sending: %s",
                        session.client_id[:8],
                        e,
                    )
                    break
                except Exception:
                    logger.warning(
                        "Failed to send event to client %s, stopping sender loop",
                        session.client_id[:8],
                        exc_info=True,
                    )
                    break

        except asyncio.CancelledError:
            logger.debug("Sender task cancelled for client %s", session.client_id[:8])
            raise

    @property
    def session_count(self) -> int:
        """Return number of active sessions."""
        return len(self._sessions)
