"""Client session management for event bus architecture (RFC-0013)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.core.event_catalog import EventMeta
    from soothe.daemon.event_bus import EventBus
    from soothe.daemon.transports.base import TransportServer

# Type alias for verbosity levels (RFC-0015, RFC-0022)
from typing import Literal

VerbosityLevel = Literal["quiet", "minimal", "normal", "detailed", "debug"]

logger = logging.getLogger(__name__)


@dataclass
class ClientSession:
    """Represents a connected client with subscriptions.

    Each client has a unique ID, event queue, and set of thread subscriptions.
    A background sender task delivers events from the queue to the client.

    Attributes:
        client_id: Unique identifier for this client
        transport: Transport server instance
        transport_client: Transport-specific client object
        subscriptions: Set of thread_ids this client is subscribed to
        event_queue: Queue for delivering events to this client
        sender_task: Background task that sends events to the client
    """

    client_id: str
    transport: TransportServer
    transport_client: Any  # Transport-specific client object
    subscriptions: set[str] = field(default_factory=set)
    event_queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(maxsize=100))
    sender_task: asyncio.Task[None] | None = None
    verbosity: VerbosityLevel = "normal"  # RFC-0022: client verbosity preference


class ClientSessionManager:
    """Manages client sessions and subscriptions.

    The session manager coordinates between the event bus and transport
    layers, handling session lifecycle, thread subscriptions, and event
    delivery.

    Args:
        event_bus: EventBus instance for routing events
    """

    def __init__(self, event_bus: EventBus) -> None:
        """Initialize session manager.

        Args:
            event_bus: EventBus instance for routing events
        """
        self._event_bus = event_bus
        self._sessions: dict[str, ClientSession] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        transport: TransportServer,
        transport_client: Any,
        client_id: str | None = None,
    ) -> str:
        """Create new client session.

        Args:
            transport: Transport server instance
            transport_client: Transport-specific client object
            client_id: Optional client ID (auto-generated if None)

        Returns:
            Unique client_id for the session
        """
        client_id = client_id or str(uuid.uuid4())

        session = ClientSession(
            client_id=client_id,
            transport=transport,
            transport_client=transport_client,
        )

        async with self._lock:
            self._sessions[client_id] = session

        # Start sender task
        session.sender_task = asyncio.create_task(self._sender_loop(session))

        logger.info("Created client session %s via %s", client_id, transport.transport_type)

        return client_id

    async def subscribe_thread(
        self,
        client_id: str,
        thread_id: str,
        verbosity: VerbosityLevel = "normal",
    ) -> None:
        """Subscribe client to receive events for thread.

        Args:
            client_id: Client identifier
            thread_id: Thread identifier to subscribe to
            verbosity: Verbosity preference (minimal|normal|detailed|debug)

        Raises:
            ValueError: If client_id not found
        """
        async with self._lock:
            session = self._sessions.get(client_id)

        if not session:
            msg = f"Client {client_id} not found"
            raise ValueError(msg)

        # Set client verbosity preference (RFC-0022)
        session.verbosity = verbosity

        topic = f"thread:{thread_id}"
        await self._event_bus.subscribe(topic, session.event_queue)
        session.subscriptions.add(thread_id)

        logger.info(
            "Client %s subscribed to thread %s with verbosity=%s",
            client_id,
            thread_id,
            verbosity,
        )

    async def unsubscribe_thread(self, client_id: str, thread_id: str) -> None:
        """Unsubscribe client from thread.

        Args:
            client_id: Client identifier
            thread_id: Thread identifier to unsubscribe from

        Raises:
            ValueError: If client_id not found
        """
        async with self._lock:
            session = self._sessions.get(client_id)

        if not session:
            msg = f"Client {client_id} not found"
            raise ValueError(msg)

        topic = f"thread:{thread_id}"
        await self._event_bus.unsubscribe(topic, session.event_queue)
        session.subscriptions.discard(thread_id)

        logger.info("Client %s unsubscribed from thread %s", client_id, thread_id)

    async def migrate_subscriptions(self, old_thread_id: str, new_thread_id: str) -> None:
        """Migrate all client subscriptions from old thread_id to new thread_id.

        This is used when a draft thread is persisted and gets a new thread_id.
        Clients subscribed to the draft thread need to be re-subscribed to the
        persisted thread.

        Args:
            old_thread_id: Original thread ID (draft)
            new_thread_id: New thread ID (persisted)
        """
        async with self._lock:
            for client_id, session in self._sessions.items():
                if old_thread_id in session.subscriptions:
                    # Unsubscribe from old topic
                    old_topic = f"thread:{old_thread_id}"
                    await self._event_bus.unsubscribe(old_topic, session.event_queue)
                    session.subscriptions.discard(old_thread_id)

                    # Subscribe to new topic
                    new_topic = f"thread:{new_thread_id}"
                    await self._event_bus.subscribe(new_topic, session.event_queue)
                    session.subscriptions.add(new_thread_id)

                    logger.info(
                        "Migrated client %s subscription: %s -> %s",
                        client_id,
                        old_thread_id[:8],
                        new_thread_id[:8],
                    )

    async def remove_session(self, client_id: str) -> None:
        """Remove client session and cleanup.

        Args:
            client_id: Client identifier to remove
        """
        async with self._lock:
            session = self._sessions.pop(client_id, None)

        if not session:
            return

        # Cancel sender task
        if session.sender_task:
            session.sender_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session.sender_task

        # Unsubscribe from all topics
        await self._event_bus.unsubscribe_all(session.event_queue)

        logger.info("Removed client session %s", client_id)

    async def get_session(self, client_id: str) -> ClientSession | None:
        """Get session by client_id.

        Args:
            client_id: Client identifier

        Returns:
            ClientSession or None if not found
        """
        async with self._lock:
            return self._sessions.get(client_id)

    async def _sender_loop(self, session: ClientSession) -> None:
        """Send events from queue with daemon-side filtering (RFC-0022).

        This task runs continuously, pulling events from the client's
        event queue, applying verbosity filtering, and sending them
        via the transport layer.

        Args:
            session: ClientSession to send events for
        """
        try:
            while True:
                # Get event data (may be tuple with metadata)
                event_data = await session.event_queue.get()

                # Extract event and metadata
                event: dict[str, Any]
                event_meta: EventMeta | None = None

                if isinstance(event_data, tuple):
                    # New format: (event, event_meta)
                    event, event_meta = event_data
                else:
                    # Legacy format: event dict without metadata
                    event = event_data

                # Daemon-side filtering (RFC-0022)
                if event_meta:
                    # Import should_show from RFC-0015's progress_verbosity
                    from soothe.ux.core.progress_verbosity import should_show

                    # Check if event should be shown at client's verbosity level
                    if not should_show(event_meta.verbosity, session.verbosity):
                        # Filter out - do not send to client
                        logger.debug(
                            "Filtered event %s for client %s (event_verbosity=%s, client_verbosity=%s)",
                            event.get("type"),
                            session.client_id,
                            event_meta.verbosity,
                            session.verbosity,
                        )
                        continue  # Skip this event

                # Send filtered event to client
                try:
                    await session.transport.send(session.transport_client, event)
                except Exception:
                    logger.exception(
                        "Failed to send event to client %s",
                        session.client_id,
                    )
                    # Transport error, stop sender loop
                    break

        except asyncio.CancelledError:
            logger.debug("Sender task cancelled for client %s", session.client_id)
            raise

    @property
    def session_count(self) -> int:
        """Return number of active sessions."""
        return len(self._sessions)
