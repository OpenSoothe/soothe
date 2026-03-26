# IG-047: Event Bus Architecture Implementation

**Implementation Guide**: 047
**Title**: Event Bus Architecture for Client Isolation
**Status**: Draft
**Created**: 2026-03-24
**Dependencies**: RFC-0013
**Estimated Effort**: 5 weeks

## Overview

This implementation guide provides step-by-step instructions for implementing the event bus architecture defined in RFC-0013. The goal is to replace the global broadcast mechanism with topic-based event routing, enabling client isolation and preventing event mixing.

### Problem Statement

Currently, the Soothe daemon broadcasts ALL events to ALL connected clients, causing:
- Event pollution (clients receive events from unrelated threads)
- No client isolation
- Security concerns (data leakage between clients)
- Scalability limitations

### Solution

Implement a pub/sub event bus architecture where:
- Each client subscribes to specific threads
- Events are routed via topics: `thread:{thread_id}`
- Only subscribed clients receive events
- Complete isolation between concurrent sessions

### Scope

**This is a HARD-CUT migration**:
- All clients must be updated atomically
- No backward compatibility maintained
- Legacy broadcast code will be removed

## Architecture Components

### 1. EventBus (`src/soothe/daemon/event_bus.py`)

**Purpose**: Async pub/sub event router with topic-based filtering.

**API**:
```python
class EventBus:
    """Async pub/sub event bus for routing events to subscribers."""

    def __init__(self):
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, topic: str, event: dict[str, Any]) -> None:
        """Publish event to all subscribers of topic.

        Args:
            topic: Topic identifier (e.g., "thread:abc123")
            event: Event dictionary to broadcast
        """
        async with self._lock:
            queues = self._subscribers.get(topic, set()).copy()

        # Send to all subscriber queues concurrently
        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "Queue full for topic %s, dropping event",
                    topic
                )

    async def subscribe(self, topic: str, queue: asyncio.Queue) -> None:
        """Subscribe queue to receive events for topic.

        Args:
            topic: Topic identifier to subscribe to
            queue: AsyncIO queue to receive events
        """
        async with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = set()
            self._subscribers[topic].add(queue)
        logger.debug("Subscribed queue to topic %s", topic)

    async def unsubscribe(self, topic: str, queue: asyncio.Queue) -> None:
        """Unsubscribe queue from topic.

        Args:
            topic: Topic identifier to unsubscribe from
            queue: Queue to remove from subscribers
        """
        async with self._lock:
            if topic in self._subscribers:
                self._subscribers[topic].discard(queue)
                if not self._subscribers[topic]:
                    del self._subscribers[topic]
        logger.debug("Unsubscribed queue from topic %s", topic)

    async def unsubscribe_all(self, queue: asyncio.Queue) -> None:
        """Unsubscribe queue from all topics.

        Args:
            queue: Queue to remove from all subscribers
        """
        async with self._lock:
            for topic in list(self._subscribers.keys()):
                self._subscribers[topic].discard(queue)
                if not self._subscribers[topic]:
                    del self._subscribers[topic]
        logger.debug("Unsubscribed queue from all topics")
```

**Implementation Notes**:
- Use `asyncio.Lock` for thread-safe subscriber management
- Use `put_nowait()` to avoid blocking on full queues
- Drop events when queue is full (configurable maxsize)
- Copy subscriber set before iteration to avoid concurrent modification

### 2. ClientSession and ClientSessionManager (`src/soothe/daemon/client_session.py`)

**Purpose**: Manage client connections, subscriptions, and event delivery.

**ClientSession Dataclass**:
```python
from dataclasses import dataclass, field
from typing import Any
import asyncio
import uuid

@dataclass
class ClientSession:
    """Represents a connected client with subscriptions."""

    client_id: str
    transport: "TransportServer"
    transport_client: Any  # Transport-specific client object
    subscriptions: set[str] = field(default_factory=set)
    event_queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=100)
    )
    sender_task: asyncio.Task | None = None

    def __post_init__(self):
        """Initialize client_id if not provided."""
        if not self.client_id:
            self.client_id = str(uuid.uuid4())
```

**ClientSessionManager Class**:
```python
class ClientSessionManager:
    """Manages client sessions and subscriptions."""

    def __init__(self, event_bus: EventBus):
        """Initialize session manager.

        Args:
            event_bus: EventBus instance for routing events
        """
        self._event_bus = event_bus
        self._sessions: dict[str, ClientSession] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        transport: "TransportServer",
        transport_client: Any,
        client_id: str | None = None
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
            transport_client=transport_client
        )

        async with self._lock:
            self._sessions[client_id] = session

        # Start sender task
        session.sender_task = asyncio.create_task(
            self._sender_loop(session)
        )

        logger.info(
            "Created client session %s via %s",
            client_id,
            transport.transport_type
        )

        return client_id

    async def subscribe_thread(self, client_id: str, thread_id: str) -> None:
        """Subscribe client to receive events for thread.

        Args:
            client_id: Client identifier
            thread_id: Thread identifier to subscribe to

        Raises:
            ValueError: If client_id not found
        """
        async with self._lock:
            session = self._sessions.get(client_id)

        if not session:
            raise ValueError(f"Client {client_id} not found")

        topic = f"thread:{thread_id}"
        await self._event_bus.subscribe(topic, session.event_queue)
        session.subscriptions.add(thread_id)

        logger.info(
            "Client %s subscribed to thread %s",
            client_id,
            thread_id
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
            try:
                await session.sender_task
            except asyncio.CancelledError:
                pass

        # Unsubscribe from all topics
        await self._event_bus.unsubscribe_all(session.event_queue)

        logger.info(
            "Removed client session %s",
            client_id
        )

    async def _sender_loop(self, session: ClientSession) -> None:
        """Send events from queue to client via transport.

        This task runs continuously, pulling events from the client's
        event queue and sending them via the transport layer.

        Args:
            session: ClientSession to send events for
        """
        try:
            while True:
                event = await session.event_queue.get()

                try:
                    await session.transport.send(
                        session.transport_client,
                        event
                    )
                except Exception as e:
                    logger.error(
                        "Failed to send event to client %s: %s",
                        session.client_id,
                        e
                    )
                    # Transport error, stop sender loop
                    break

        except asyncio.CancelledError:
            logger.debug("Sender task cancelled for client %s", session.client_id)
            raise

    async def get_session(self, client_id: str) -> ClientSession | None:
        """Get session by client_id.

        Args:
            client_id: Client identifier

        Returns:
            ClientSession or None if not found
        """
        async with self._lock:
            return self._sessions.get(client_id)

    @property
    def session_count(self) -> int:
        """Return number of active sessions."""
        return len(self._sessions)
```

### 3. Transport Protocol Extension (`src/soothe/daemon/transports/base.py`)

**Purpose**: Add `send()` method to TransportServer protocol.

**Protocol Definition**:
```python
from typing import Protocol, Any

class TransportServer(Protocol):
    """Transport server protocol for multi-transport support."""

    @property
    def transport_type(self) -> str:
        """Return transport type identifier."""
        ...

    async def start(self) -> None:
        """Start the transport server."""
        ...

    async def stop(self) -> None:
        """Stop the transport server and disconnect all clients."""
        ...

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast message to all connected clients (deprecated).

        This method is retained for backward compatibility but
        should not be used in new code. Use send() instead.
        """
        ...

    async def send(self, client: Any, message: dict[str, Any]) -> None:
        """Send message to specific client.

        Args:
            client: Transport-specific client object
            message: Message dictionary to send

        Raises:
            ConnectionError: If client connection is broken
        """
        ...

    @property
    def client_count(self) -> int:
        """Return number of connected clients."""
        ...
```

## Implementation Steps

### Phase 1: Core Infrastructure (Week 1)

#### Step 1.1: Create EventBus

**File**: `src/soothe/daemon/event_bus.py`

1. Implement `EventBus` class with the API shown above
2. Add comprehensive unit tests:
   - Test publish to single subscriber
   - Test publish to multiple subscribers
   - Test subscribe/unsubscribe
   - Test queue overflow handling
   - Test concurrent publishers

**Test File**: `tests/unit/test_event_bus.py`

```python
import asyncio
import pytest
from soothe.daemon.event_bus import EventBus

@pytest.mark.asyncio
async def test_publish_to_single_subscriber():
    """Test publishing event to one subscriber."""
    bus = EventBus()
    queue = asyncio.Queue()

    await bus.subscribe("thread:abc123", queue)

    event = {"type": "test", "data": "hello"}
    await bus.publish("thread:abc123", event)

    received = await queue.get()
    assert received == event

@pytest.mark.asyncio
async def test_publish_to_multiple_subscribers():
    """Test publishing event to multiple subscribers."""
    bus = EventBus()
    queue1 = asyncio.Queue()
    queue2 = asyncio.Queue()

    await bus.subscribe("thread:abc123", queue1)
    await bus.subscribe("thread:abc123", queue2)

    event = {"type": "test", "data": "hello"}
    await bus.publish("thread:abc123", event)

    assert await queue1.get() == event
    assert await queue2.get() == event

@pytest.mark.asyncio
async def test_unsubscribe():
    """Test unsubscribing from topic."""
    bus = EventBus()
    queue = asyncio.Queue()

    await bus.subscribe("thread:abc123", queue)
    await bus.unsubscribe("thread:abc123", queue)

    event = {"type": "test", "data": "hello"}
    await bus.publish("thread:abc123", event)

    # Queue should be empty
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.1)

@pytest.mark.asyncio
async def test_queue_overflow():
    """Test that events are dropped when queue is full."""
    bus = EventBus()
    # Queue with maxsize=1
    queue = asyncio.Queue(maxsize=1)

    await bus.subscribe("thread:abc123", queue)

    # Send 3 events, only first should be delivered
    for i in range(3):
        await bus.publish("thread:abc123", {"type": "test", "data": i})

    # Only one event in queue
    event = await queue.get()
    assert event["data"] == 0

    # Queue is now empty (overflow events dropped)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.1)
```

#### Step 1.2: Create ClientSession and ClientSessionManager

**File**: `src/soothe/daemon/client_session.py`

1. Implement `ClientSession` dataclass
2. Implement `ClientSessionManager` class
3. Add comprehensive unit tests:
   - Test session creation
   - Test thread subscription
   - Test session removal
   - Test sender loop
   - Test concurrent sessions

**Test File**: `tests/unit/test_client_session.py`

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from soothe.daemon.client_session import ClientSession, ClientSessionManager
from soothe.daemon.event_bus import EventBus

@pytest.mark.asyncio
async def test_create_session():
    """Test session creation."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.transport_type = "test"

    client_id = await manager.create_session(
        transport=transport,
        transport_client=None
    )

    assert client_id is not None
    session = await manager.get_session(client_id)
    assert session is not None
    assert session.transport == transport
    assert len(session.subscriptions) == 0

@pytest.mark.asyncio
async def test_subscribe_thread():
    """Test thread subscription."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    client_id = await manager.create_session(transport, None)

    await manager.subscribe_thread(client_id, "thread-abc123")

    session = await manager.get_session(client_id)
    assert "thread-abc123" in session.subscriptions

@pytest.mark.asyncio
async def test_sender_loop_sends_events():
    """Test that sender loop sends events via transport."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.send = AsyncMock()

    client_id = await manager.create_session(transport, None)
    await manager.subscribe_thread(client_id, "thread-abc123")

    # Publish event
    event = {"type": "test", "data": "hello"}
    await bus.publish("thread:abc123", event)

    # Wait for sender loop to process
    await asyncio.sleep(0.1)

    # Transport.send should have been called
    transport.send.assert_called_once()
```

#### Step 1.3: Create Transport Protocol

**File**: `src/soothe/daemon/transports/base.py`

1. Define `TransportServer` protocol with `send()` method
2. Document the protocol in docstrings
3. Add type hints

### Phase 2: Daemon Server Integration (Week 2)

#### Step 2.1: Update SootheDaemon

**File**: `src/soothe/daemon/server.py`

**Changes**:

1. **Initialize EventBus and ClientSessionManager** (in `__init__`):

```python
from soothe.daemon.event_bus import EventBus
from soothe.daemon.client_session import ClientSessionManager

class SootheDaemon:
    def __init__(self, config: SootheConfig | None = None):
        # ... existing init ...
        self._event_bus = EventBus()
        self._session_manager = ClientSessionManager(self._event_bus)
```

2. **Replace `_broadcast()` method**:

```python
async def _broadcast(self, msg: dict[str, Any]) -> None:
    """Route event to appropriate subscribers via event bus.

    Events are published to thread-specific topics. Only clients
    subscribed to the thread will receive the event.
    """
    thread_id = msg.get("thread_id") or self._runner.current_thread_id

    if thread_id:
        topic = f"thread:{thread_id}"
        logger.debug("Publishing event to topic %s: %s", topic, msg.get("type"))
        await self._event_bus.publish(topic, msg)
    else:
        logger.warning(
            "Event has no thread_id, cannot route: %s",
            msg.get("type")
        )
```

3. **Remove legacy broadcast code**:
   - Delete the loop over `self._clients`
   - Delete the legacy writer.drain() code
   - Remove `_send()` method if unused

#### Step 2.2: Update Message Handlers

**File**: `src/soothe/daemon/_handlers.py`

**Changes**:

1. **Add subscription message handler** (around line 84):

```python
async def _handle_client_message(
    self,
    client_id: str,  # Changed from _ClientConn | None
    msg: dict[str, Any],
) -> None:
    """Handle a message from a client.

    Args:
        client_id: Unique client identifier
        msg: Message dict from the client
    """
    msg_type = msg.get("type", "")

    # NEW: Handle thread subscription
    if msg_type == "subscribe_thread":
        thread_id = msg.get("thread_id", "").strip()
        if not thread_id:
            await self._broadcast({
                "type": "error",
                "code": "INVALID_MESSAGE",
                "message": "subscribe_thread requires thread_id"
            })
            return

        try:
            await self._session_manager.subscribe_thread(client_id, thread_id)

            # Send confirmation
            session = await self._session_manager.get_session(client_id)
            await session.transport.send(
                session.transport_client,
                {
                    "type": "subscription_confirmed",
                    "thread_id": thread_id,
                    "client_id": client_id
                }
            )
        except ValueError as e:
            logger.error("Subscription failed: %s", e)
            session = await self._session_manager.get_session(client_id)
            if session:
                await session.transport.send(
                    session.transport_client,
                    {
                        "type": "error",
                        "code": "SUBSCRIPTION_FAILED",
                        "message": str(e)
                    }
                )
        return

    # ... existing handlers ...
```

2. **Update all handler calls to pass client_id**:
   - Remove any usage of `client` parameter (the old `_ClientConn` object)
   - Use `client_id` string instead
   - Update `_handle_transport_message()` to pass client_id

3. **Update `_handle_transport_message()`**:

```python
def _handle_transport_message(self, client_id: str, msg: dict[str, Any]) -> None:
    """Handle incoming message from transport layer.

    Args:
        client_id: Unique client identifier
        msg: Message dict from a transport client
    """
    task = asyncio.create_task(self._handle_client_message(client_id, msg))
    _ = task  # Suppress RUF006 warning
```

### Phase 3: Transport Layer Updates (Week 3)

#### Step 3.1: Update Unix Socket Transport

**File**: `src/soothe/daemon/transports/unix_socket.py`

**Changes**:

1. **Update `_ClientConn` dataclass**:

```python
from dataclasses import dataclass
import asyncio

@dataclass
class _ClientConn:
    """Unix socket client connection."""
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    client_id: str | None = None  # NEW: set by session manager
```

2. **Call session manager on connect** (in `_handle_client`):

```python
async def _handle_client(self, reader: StreamReader, writer: StreamWriter):
    """Handle a connected client.

    Args:
        reader: Stream reader for client
        writer: Stream writer for client
    """
    client = _ClientConn(reader=reader, writer=writer)

    # Create session
    client.client_id = await self._session_manager.create_session(
        transport=self,
        transport_client=client
    )

    logger.info(
        "Client %s connected via Unix socket (total=%d)",
        client.client_id,
        self.client_count
    )

    try:
        # Handle messages
        async for line in reader:
            try:
                msg = decode(line)
                if self._message_handler:
                    self._message_handler(client.client_id, msg)  # Pass client_id
            except Exception as e:
                logger.error("Error handling message: %s", e)
    finally:
        # Cleanup
        if client.client_id:
            await self._session_manager.remove_session(client.client_id)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        logger.info("Client disconnected (total=%d)", self.client_count)
```

3. **Implement `send()` method**:

```python
async def send(self, client: _ClientConn, message: dict[str, Any]) -> None:
    """Send message to specific client.

    Args:
        client: Client connection object
        message: Message dictionary to send

    Raises:
        ConnectionError: If write fails
    """
    try:
        data = encode(message)
        client.writer.write(data)
        await client.writer.drain()
    except Exception as e:
        logger.error("Failed to send to client %s: %s", client.client_id, e)
        raise ConnectionError(f"Failed to send: {e}") from e
```

4. **Remove `broadcast()` method or mark as deprecated**:

```python
async def broadcast(self, message: dict[str, Any]) -> None:
    """Broadcast message to all clients (DEPRECATED).

    This method is no longer used. Event routing is handled by
    the EventBus and ClientSessionManager.
    """
    logger.warning("broadcast() is deprecated, use EventBus.publish() instead")
    # No-op
```

#### Step 3.2: Update WebSocket Transport

**File**: `src/soothe/daemon/transports/websocket.py`

**Changes** (similar to Unix socket):

1. Add `client_id` tracking in client data dict
2. Call `session_manager.create_session()` on connect
3. Implement `send()` method
4. Deprecate `broadcast()` method
5. Pass `client_id` to message handler

#### Step 3.3: Update HTTP REST Transport

**File**: `src/soothe/daemon/transports/http_rest.py`

**Changes**:

1. For REST API, clients don't maintain persistent connections
2. Add `/api/v1/threads/{thread_id}/subscribe` endpoint
3. Use session manager for clients that want streaming

### Phase 4: Client Updates - BREAKING CHANGE (Week 4)

#### Step 4.1: Update DaemonClient

**File**: `src/soothe/daemon/client.py`

**Changes**:

1. **Add `subscribe_thread()` method**:

```python
async def subscribe_thread(self, thread_id: str) -> None:
    """Subscribe to receive events for a thread.

    Args:
        thread_id: Thread identifier to subscribe to

    Raises:
        ConnectionError: If not connected
    """
    if not self._writer:
        raise ConnectionError("Not connected to daemon")

    msg = {
        "type": "subscribe_thread",
        "thread_id": thread_id
    }
    self._writer.write(encode(msg))
    await self._writer.drain()

    logger.info("Subscribed to thread %s", thread_id)
```

2. **Add helper to wait for confirmation**:

```python
async def wait_for_subscription_confirmed(self, thread_id: str, timeout: float = 5.0) -> None:
    """Wait for subscription confirmation message.

    Args:
        thread_id: Expected thread ID
        timeout: Maximum seconds to wait

    Raises:
        TimeoutError: If confirmation not received
        ValueError: If confirmation has different thread_id
    """
    async with asyncio.timeout(timeout):
        event = await self.read_event()

    if event.get("type") != "subscription_confirmed":
        raise ValueError(f"Expected subscription_confirmed, got {event.get('type')}")

    if event.get("thread_id") != thread_id:
        raise ValueError(
            f"Subscription thread_id mismatch: expected {thread_id}, "
            f"got {event.get('thread_id')}"
        )
```

#### Step 4.2: Update TUI Application

**File**: `src/soothe/ux/tui/app.py`

**Changes** (around line 218-242):

```python
async def _connect_to_daemon(self) -> None:
    """Connect to daemon and setup session."""
    try:
        self._client = DaemonClient()
        await self._client.connect()

        # Resume or create thread
        if self._thread_id:
            await self._client.send_resume_thread(self._thread_id)
        else:
            await self._client.send_new_thread()

        # Wait for status message with thread_id
        status = await self._client.read_event()
        if status.get("type") != "status":
            raise RuntimeError(f"Expected status, got {status.get('type')}")

        thread_id = status.get("thread_id")
        if not thread_id:
            raise RuntimeError("No thread_id in status message")

        self._thread_id = thread_id

        # NEW: Subscribe to thread
        await self._client.subscribe_thread(thread_id)
        await self._client.wait_for_subscription_confirmed(thread_id)

        self._connected = True
        self._state.state = status.get("state", "idle")
        self._state.client_id = status.get("client_id")

        logger.info(
            "Connected to daemon, thread=%s, client=%s",
            thread_id,
            self._state.client_id
        )

    except Exception as e:
        logger.error("Failed to connect to daemon: %s", e)
        self._connected = False
```

#### Step 4.3: Update Headless Runner

**File**: `src/soothe/ux/cli/execution/daemon_runner.py`

**Changes** (around line 43-68):

```python
async def run(self, text: str, **kwargs) -> None:
    """Run query in daemon mode.

    Args:
        text: User input text
        **kwargs: Additional arguments
    """
    client = DaemonClient()
    await client.connect()

    # Resume or create thread
    if self._thread_id:
        await client.send_resume_thread(self._thread_id)
    else:
        await client.send_new_thread()

    # Get thread_id from status
    status = await client.read_event()
    thread_id = status.get("thread_id")

    # NEW: Subscribe to thread
    await client.subscribe_thread(thread_id)
    await client.wait_for_subscription_confirmed(thread_id)

    # Send input
    await client.send_input(text, **kwargs)

    # Stream events
    while True:
        event = await client.read_event()

        if event.get("type") == "status" and event.get("state") == "idle":
            break

        # Process event
        render_event(event)

    await client.disconnect()
```

#### Step 4.4: Remove Legacy Code

**Files**: Multiple

1. Remove old `_broadcast()` fan-out logic from `server.py`
2. Remove `client` parameter of type `_ClientConn | None` from handlers
3. Remove any backward compatibility code
4. Clean up unused imports

### Phase 5: Testing & Documentation (Week 5)

#### Step 5.1: Add Integration Tests

**File**: `tests/integration/test_daemon_multi_client.py`

```python
import asyncio
import pytest
from soothe.daemon.client import DaemonClient

@pytest.mark.asyncio
async def test_two_clients_isolated():
    """Test that two clients don't receive each other's events."""
    # Start daemon
    daemon = await start_daemon()

    # Client 1 creates thread and subscribes
    client1 = DaemonClient()
    await client1.connect()
    await client1.send_new_thread()
    status1 = await client1.read_event()
    thread1 = status1["thread_id"]
    await client1.subscribe_thread(thread1)
    await client1.wait_for_subscription_confirmed(thread1)

    # Client 2 creates different thread and subscribes
    client2 = DaemonClient()
    await client2.connect()
    await client2.send_new_thread()
    status2 = await client2.read_event()
    thread2 = status2["thread_id"]
    await client2.subscribe_thread(thread2)
    await client2.wait_for_subscription_confirmed(thread2)

    # Client 1 sends input
    await client1.send_input("Query from client 1")

    # Client 1 should receive events
    event = await asyncio.wait_for(client1.read_event(), timeout=1.0)
    assert event.get("type") == "status"
    assert event.get("thread_id") == thread1

    # Client 2 should NOT receive events from client 1's thread
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(client2.read_event(), timeout=0.5)

    await client1.disconnect()
    await client2.disconnect()
    await daemon.stop()

@pytest.mark.asyncio
async def test_unsubscribed_client_receives_nothing():
    """Test that client without subscription receives no events."""
    daemon = await start_daemon()

    # Client connects but doesn't subscribe
    client = DaemonClient()
    await client.connect()
    await client.send_new_thread()
    status = await client.read_event()

    # Another client runs a query
    client2 = DaemonClient()
    await client2.connect()
    await client2.send_new_thread()
    status2 = await client2.read_event()
    thread2 = status2["thread_id"]
    await client2.subscribe_thread(thread2)
    await client2.wait_for_subscription_confirmed(thread2)
    await client2.send_input("Query")

    # First client should receive nothing
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(client.read_event(), timeout=1.0)

    await client.disconnect()
    await client2.disconnect()
    await daemon.stop()
```

#### Step 5.2: Add Stress Tests

**File**: `tests/stress/test_event_bus_performance.py`

```python
import asyncio
import pytest
from soothe.daemon.event_bus import EventBus

@pytest.mark.asyncio
async def test_many_concurrent_publishers():
    """Test event bus with many concurrent publishers."""
    bus = EventBus()
    queue = asyncio.Queue(maxsize=1000)
    await bus.subscribe("thread:test", queue)

    async def publish_events(n: int):
        for i in range(n):
            await bus.publish("thread:test", {"id": i})

    # 10 concurrent publishers, 100 events each
    tasks = [publish_events(100) for _ in range(10)]
    await asyncio.gather(*tasks)

    # Should have ~1000 events (some may be dropped)
    assert queue.qsize() > 500
```

#### Step 5.3: Update Documentation

**Files to Update**:

1. `docs/user_guide.md` - Add thread subscription explanation
2. `docs/specs/RFC-0013.md` - Already updated
3. `docs/impl/README.md` - Add IG-047 to index
4. `CHANGELOG.md` - Document breaking changes

## Testing Checklist

### Unit Tests

- [ ] EventBus publish to single subscriber
- [ ] EventBus publish to multiple subscribers
- [ ] EventBus subscribe/unsubscribe
- [ ] EventBus queue overflow handling
- [ ] EventBus concurrent publishers
- [ ] ClientSession creation
- [ ] ClientSession subscription
- [ ] ClientSession removal
- [ ] ClientSessionManager concurrent sessions
- [ ] Transport send() method

### Integration Tests

- [ ] Two clients isolated (different threads)
- [ ] Unsubscribed client receives nothing
- [ ] Client reconnection after disconnect
- [ ] Multiple subscriptions per client
- [ ] Event routing with correct thread_id
- [ ] Queue overflow drops old events
- [ ] Session cleanup on disconnect

### End-to-End Tests

- [ ] TUI can run queries and receive events
- [ ] CLI headless mode works
- [ ] WebSocket client can connect and subscribe
- [ ] Multiple clients can run simultaneously
- [ ] Events don't mix between TUI and CLI
- [ ] Performance: 100 concurrent clients

### Manual Testing

- [ ] Start daemon: `soothe server start`
- [ ] Connect TUI: `soothe tui`
- [ ] In another terminal: `soothe run "test query"`
- [ ] Verify TUI doesn't see CLI events
- [ ] Verify CLI output is correct
- [ ] Check logs for client_id and thread_id

## Migration Checklist for External Clients

If you have custom clients using the Soothe daemon protocol:

### Required Changes

1. **Add subscription after connection**:
   ```python
   # After connecting and getting thread_id
   client.send({"type": "subscribe_thread", "thread_id": thread_id})
   ```

2. **Handle new message types**:
   - `subscription_confirmed` - Acknowledges subscription
   - Events now include `thread_id` field

3. **Update status message handling**:
   - Status now includes `client_id` field
   - Store client_id for logging/debugging

### Removed Functionality

- **No global broadcast** - Clients won't receive any events without subscription
- **No backward compatibility** - Old clients will fail silently

### Testing Your Client

1. Connect to daemon
2. Send `new_thread` or `resume_thread`
3. Extract `thread_id` from status message
4. Send `subscribe_thread` with that thread_id
5. Wait for `subscription_confirmed`
6. Now send input and receive events

## Performance Considerations

### Event Queue Sizing

- Default queue size: 100 events
- If client is slow, events will be dropped
- Tune `maxsize` based on expected throughput:
  - Interactive mode: 100 (default)
  - High-throughput: 1000
  - Never unbounded (memory leak risk)

### Memory Usage

- Each session: ~10KB (queue + data structures)
- 100 sessions: ~1MB
- 1000 sessions: ~10MB (acceptable)

### CPU Usage

- EventBus uses lock-free reads (copy subscriber set)
- Publish is O(n) where n = number of subscribers
- Most work is in transport send, not routing

## Troubleshooting

### Client Not Receiving Events

**Symptoms**: Client connects but sees no events

**Causes**:
1. Client didn't send `subscribe_thread`
2. Thread_id mismatch
3. Queue full (events dropped)

**Solutions**:
1. Check subscription is sent after thread creation
2. Verify thread_id matches in subscribe message
3. Check logs for "Queue full" warnings

### Events From Wrong Thread

**Symptoms**: Client receives events from different thread

**Causes**:
1. Client subscribed to wrong thread_id
2. Bug in event routing

**Solutions**:
1. Check `subscription_confirmed` has correct thread_id
2. Verify EventBus publish uses correct topic
3. Add logging to see which topic events go to

### Memory Leak

**Symptoms**: Memory grows over time

**Causes**:
1. Sessions not cleaned up on disconnect
2. Sender tasks not cancelled

**Solutions**:
1. Ensure `remove_session()` is called on disconnect
2. Check sender task is cancelled
3. Monitor session count in logs

## Files Changed Summary

### New Files

- `src/soothe/daemon/event_bus.py` - EventBus implementation
- `src/soothe/daemon/client_session.py` - ClientSession and ClientSessionManager
- `src/soothe/daemon/transports/base.py` - Transport protocol with send()
- `tests/unit/test_event_bus.py` - EventBus unit tests
- `tests/unit/test_client_session.py` - ClientSession unit tests
- `tests/integration/test_daemon_multi_client.py` - Integration tests

### Modified Files

- `src/soothe/daemon/server.py` - Integrate EventBus, replace _broadcast()
- `src/soothe/daemon/_handlers.py` - Add subscription handling, use client_id
- `src/soothe/daemon/transports/unix_socket.py` - Add session management, implement send()
- `src/soothe/daemon/transports/websocket.py` - Add session management, implement send()
- `src/soothe/daemon/transport_manager.py` - Update for session management
- `src/soothe/daemon/client.py` - Add subscribe_thread() method
- `src/soothe/ux/tui/app.py` - Subscribe to thread after connection
- `src/soothe/ux/cli/execution/daemon_runner.py` - Subscribe in headless mode

## Success Criteria

Implementation is complete when:

1. ✅ All unit tests pass (>90% coverage)
2. ✅ All integration tests pass
3. ✅ Manual multi-client testing works
4. ✅ TUI can run queries and receive events
5. ✅ CLI headless mode works
6. ✅ Multiple clients don't see each other's events
7. ✅ Documentation is updated
8. ✅ CHANGELOG.md updated with breaking changes
9. ✅ Code passes `make lint`
10. ✅ Performance benchmarks acceptable (100 concurrent clients)

---

*This implementation guide provides the complete roadmap for implementing event bus architecture in Soothe. Follow the phases in order, and don't skip the testing phases!*