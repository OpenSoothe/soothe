# Implementation Guide: Daemon-Side Event Filtering

**IG Number**: 081
**Title**: Daemon-Side Event Filtering Implementation
**RFC**: RFC-401
**Status**: Completed
**Created**: 2026-03-28
**Dependencies**: RFC-400, RFC-401, RFC-401

## Overview

This guide implements RFC-401: Daemon-Side Event Filtering Protocol. The implementation extends RFC-400's subscription protocol to support daemon-side event filtering based on client verbosity preferences, reducing network bandwidth and client processing overhead by an estimated 60-70%.

**Key Changes**:
1. Extend `subscribe_thread` protocol message with optional `verbosity` field
2. Add `verbosity` preference to `ClientSession` dataclass
3. Enhance `EventBus.publish()` to pass event metadata for filtering
4. Implement filtering logic in `ClientSessionManager._sender_loop()`
5. Update all event emission sites to pass event metadata
6. Update clients to specify verbosity preferences

**Performance Goal**: 60-70% reduction in event transfer for clients at 'normal' verbosity.

## Implementation Phases

### Phase 1: Daemon Infrastructure (Files 1-5)

**Goal**: Implement daemon-side filtering infrastructure

**Files Modified**:
1. `src/soothe/daemon/client_session.py` - Add verbosity field and filtering logic
2. `src/soothe/daemon/event_bus.py` - Pass event metadata through queues
3. `src/soothe/daemon/_handlers.py` - Handle verbosity in subscribe_thread
4. `src/soothe/protocols/concurrency.py` - Add VerbosityLevel type import (if needed)
5. Tests for daemon filtering

### Phase 2: Event Emission Updates (Files 6-15)

**Goal**: Update all event emission sites to pass metadata

**Files Modified**:
6. `src/soothe/core/runner.py` - Main event emission
7. `src/soothe/cognition/goal_engine.py` - Goal events
8. `src/soothe/cognition/agent_loop/core/agent.py` - Agentic loop events
9. Backend modules (context, memory, plan, policy, durability)
10. Subagent modules (browser, claude, research, skillify, weaver)
11. Tool modules (execution, file_ops, web_search, etc.)
12. Tests for metadata propagation

### Phase 3: Client Updates (Files 16-20)

**Goal**: Update clients to specify verbosity preferences

**Files Modified**:
13. `src/soothe/daemon/client.py` - Client library
14. `src/soothe/ux/tui/app.py` - TUI client
15. `src/soothe/ux/cli/execution/daemon_runner.py` - CLI headless
16. `src/soothe/ux/cli/execution/standalone.py` - Standalone mode (if needed)
17. WebSocket client examples
18. Integration tests

### Phase 4: Verification (File 19)

**Goal**: Run full verification suite

**File**: `scripts/verify_finally.sh` - Ensure all tests pass

---

## File 1: `src/soothe/daemon/client_session.py`

### Changes

**1.1 Add imports**:
```python
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from soothe.core.event_catalog import EventMeta

# Type alias for verbosity levels (from RFC-401)
VerbosityLevel = Literal["minimal", "normal", "detailed", "debug"]
```

**1.2 Add `verbosity` field to `ClientSession` dataclass**:
```python
@dataclass
class ClientSession:
    """Represents a connected client with subscriptions."""

    client_id: str
    transport: TransportServer
    transport_client: Any
    subscriptions: set[str] = field(default_factory=set)
    event_queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=100)
    )
    sender_task: asyncio.Task[None] | None = None
    verbosity: VerbosityLevel = "normal"  # NEW: client verbosity preference
```

**1.3 Update `subscribe_thread()` method**:
```python
async def subscribe_thread(
    self,
    client_id: str,
    thread_id: str,
    verbosity: VerbosityLevel = "normal",  # NEW parameter
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

    # Set client verbosity preference
    session.verbosity = verbosity  # NEW: set verbosity

    topic = f"thread:{thread_id}"
    await self._event_bus.subscribe(topic, session.event_queue)
    session.subscriptions.add(thread_id)

    logger.info(
        "Client %s subscribed to thread %s with verbosity=%s",
        client_id,
        thread_id,
        verbosity,
    )
```

**1.4 Update `_sender_loop()` method to filter events**:
```python
async def _sender_loop(self, session: ClientSession) -> None:
    """Send events from queue with daemon-side filtering.

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

            # Daemon-side filtering (RFC-401)
            if event_meta:
                # Import should_show from RFC-401's progress_verbosity
                from soothe.ux.core.progress_verbosity import should_show

                # Check if event should be shown at client's verbosity level
                if not should_show(event_meta.verbosity, session.verbosity):
                    # Filter out - do not send to client
                    logger.debug(
                        "Filtered event %s for client %s "
                        "(event_verbosity=%s, client_verbosity=%s)",
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
```

**1.5 Update logging to include verbosity**:
```python
logger.info(
    "Created client session %s via %s with verbosity=%s",
    client_id,
    transport.transport_type,
    session.verbosity,
)
```

### Testing

**Unit Test**: `tests/unit/daemon/test_client_session.py`
```python
async def test_subscribe_with_verbosity():
    """Test subscription with verbosity preference."""
    event_bus = EventBus()
    manager = ClientSessionManager(event_bus)

    client_id = await manager.create_session(mock_transport, mock_client)
    await manager.subscribe_thread(client_id, "thread-123", verbosity="detailed")

    session = await manager.get_session(client_id)
    assert session.verbosity == "detailed"

async def test_event_filtering():
    """Test daemon-side event filtering."""
    # ... test that events are filtered based on verbosity
```

---

## File 2: `src/soothe/daemon/event_bus.py`

### Changes

**2.1 Add import**:
```python
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.core.event_catalog import EventMeta
```

**2.2 Update `publish()` method signature**:
```python
async def publish(
    self,
    topic: str,
    event: dict[str, Any],
    event_meta: EventMeta | None = None,  # NEW: optional metadata
) -> None:
    """Publish event to all subscribers of topic.

    Args:
        topic: Topic identifier (e.g., "thread:abc123")
        event: Event dictionary to broadcast
        event_meta: Optional EventMeta for filtering (RFC-401)
    """
    async with self._lock:
        queues = self._subscribers.get(topic, set()).copy()

    if not queues:
        logger.debug("No subscribers for topic %s", topic)
        return

    # Send (event, event_meta) tuple to queues for filtering
    dropped = 0
    for queue in queues:
        try:
            queue.put_nowait((event, event_meta))  # NEW: tuple with metadata
        except asyncio.QueueFull:
            dropped += 1
            logger.warning("Queue full for topic %s, dropping event", topic)

    logger.debug(
        "Published event %s to topic %s: %d delivered, %d dropped",
        event.get("type"),
        topic,
        len(queues) - dropped,
        dropped,
    )
```

### Testing

**Unit Test**: `tests/unit/daemon/test_event_bus.py`
```python
async def test_publish_with_metadata():
    """Test publishing event with metadata."""
    bus = EventBus()
    queue = asyncio.Queue()
    await bus.subscribe("thread:abc", queue)

    event = {"type": "test.event"}
    meta = mock_event_meta()  # Mock EventMeta
    await bus.publish("thread:abc", event, event_meta=meta)

    result = await queue.get()
    assert result == (event, meta)
```

---

## File 3: `src/soothe/daemon/_handlers.py`

### Changes

**3.1 Update `handle_subscribe_thread()` method**:
```python
async def handle_subscribe_thread(
    self,
    client_id: str,
    message: dict[str, Any],
) -> None:
    """Handle subscribe_thread message with optional verbosity.

    Args:
        client_id: Client identifier
        message: Message dict with thread_id and optional verbosity
    """
    thread_id = message.get("thread_id", "")
    verbosity = message.get("verbosity", "normal")  # NEW: optional, default='normal'

    if not thread_id:
        await self._send_error(
            client_id,
            "INVALID_MESSAGE",
            "Missing required field: thread_id",
        )
        return

    # Validate verbosity value
    valid_verbosity = {"minimal", "normal", "detailed", "debug"}
    if verbosity not in valid_verbosity:
        await self._send_error(
            client_id,
            "INVALID_MESSAGE",
            f"Invalid verbosity value: {verbosity}. "
            f"Must be one of: {', '.join(valid_verbosity)}",
        )
        return

    # Subscribe with verbosity preference
    try:
        await self._session_manager.subscribe_thread(
            client_id,
            thread_id,
            verbosity=verbosity,
        )
    except ValueError as e:
        await self._send_error(client_id, "INVALID_CLIENT", str(e))
        return

    # Send subscription confirmation with echoed verbosity
    await self._send_message(
        client_id,
        {
            "type": "subscription_confirmed",
            "thread_id": thread_id,
            "client_id": client_id,
            "verbosity": verbosity,  # NEW: echo verbosity
        },
    )

    logger.info(
        "Client %s subscribed to thread %s with verbosity=%s",
        client_id,
        thread_id,
        verbosity,
    )
```

### Testing

**Unit Test**: `tests/unit/daemon/test_handlers.py`
```python
async def test_subscribe_with_verbosity():
    """Test subscribe_thread with verbosity parameter."""
    handler = DaemonHandlersMixin()

    message = {
        "type": "subscribe_thread",
        "thread_id": "thread-123",
        "verbosity": "detailed",
    }

    await handler.handle_subscribe_thread("client-456", message)

    # Verify subscription with verbosity
    # ...

async def test_subscribe_invalid_verbosity():
    """Test subscription with invalid verbosity."""
    handler = DaemonHandlersMixin()

    message = {
        "type": "subscribe_thread",
        "thread_id": "thread-123",
        "verbosity": "invalid",
    }

    await handler.handle_subscribe_thread("client-456", message)

    # Verify error response
    # ...
```

---

## File 4: Event Emission Sites (Multiple Files)

### Pattern for All Emission Sites

**Before (current)**:
```python
await self._event_bus.publish(topic, event_dict)
```

**After (proposed)**:
```python
from soothe.core.event_catalog import REGISTRY

# Get event metadata for filtering
event_type = event_dict.get("type", "")
event_meta = REGISTRY.get_meta(event_type) if event_type else None

# Publish with metadata
await self._event_bus.publish(topic, event_dict, event_meta=event_meta)
```

### Files to Update

**4.1** `src/soothe/core/runner.py`:
- `_runner_phases.py` integration
- `_runner_steps.py` integration
- `_runner_autonomous.py` integration
- All `yield _custom(event_dict)` calls

**4.2** `src/soothe/cognition/goal_engine.py`:
- Goal events emission

**4.3** `src/soothe/cognition/agent_loop/core/agent.py`:
- Agentic loop events

**4.4** Backend modules:
- `src/soothe/backends/context/` - Context events
- `src/soothe/backends/memory/` - Memory events
- `src/soothe/cognition/planning/` - Plan events
- `src/soothe/backends/policy/` - Policy events
- `src/soothe/backends/durability/` - Durability events

**4.5** Subagent modules:
- `src/soothe/subagents/browser/` - Browser events
- `src/soothe/subagents/claude/` - Claude events
- `src/soothe/subagents/research/` - Research events
- `src/soothe/subagents/skillify/` - Skillify events
- `src/soothe/subagents/weaver/` - Weaver events

**4.6** Tool modules:
- `src/soothe/tools/execution/` - Execution events
- `src/soothe/tools/file_ops/` - File operation events
- `src/soothe/tools/web_search/` - Web search events
- All other tool modules

### Helper Function (Optional)

Create utility to reduce boilerplate:

**File**: `src/soothe/utils/event_emission.py`:
```python
"""Helper utilities for event emission with metadata."""
from typing import Any

from soothe.core.event_catalog import REGISTRY, EventMeta


def prepare_event_for_publish(event_dict: dict[str, Any]) -> tuple[dict[str, Any], EventMeta | None]:
    """Prepare event dict for publishing with metadata.

    Args:
        event_dict: Event dictionary

    Returns:
        Tuple of (event_dict, event_meta) for EventBus.publish()
    """
    event_type = event_dict.get("type", "")
    event_meta = REGISTRY.get_meta(event_type) if event_type else None
    return event_dict, event_meta
```

**Usage**:
```python
from soothe.utils.event_emission import prepare_event_for_publish

event_dict, event_meta = prepare_event_for_publish({"type": "soothe.protocol.plan.created", ...})
await self._event_bus.publish(topic, event_dict, event_meta=event_meta)
```

---

## File 5: `src/soothe/daemon/client.py`

### Changes

**5.1 Add verbosity parameter to `subscribe_thread()`**:
```python
from typing import Literal

VerbosityLevel = Literal["minimal", "normal", "detailed", "debug"]


async def subscribe_thread(
    self,
    thread_id: str,
    verbosity: VerbosityLevel = "normal",  # NEW parameter
) -> None:
    """Subscribe to receive events for a thread.

    Args:
        thread_id: Thread identifier to subscribe to
        verbosity: Verbosity preference (minimal|normal|detailed|debug)

    Raises:
        ProtocolError: If subscription fails
    """
    await self._send({
        "type": "subscribe_thread",
        "thread_id": thread_id,
        "verbosity": verbosity,  # NEW: include verbosity
    })

    # Wait for subscription_confirmed
    response = await self._receive()
    if response.get("type") != "subscription_confirmed":
        raise ProtocolError(f"Expected subscription_confirmed, got {response.get('type')}")

    # Verify echoed verbosity matches
    echoed_verbosity = response.get("verbosity")
    if echoed_verbosity != verbosity:
        logger.warning(
            "Verbosity mismatch: requested=%s, received=%s",
            verbosity,
            echoed_verbosity,
        )

    logger.info(
        "Subscribed to thread %s with verbosity=%s",
        thread_id,
        verbosity,
    )
```

---

## File 6: `src/soothe/ux/tui/app.py`

### Changes

**6.1 Update subscription to specify verbosity**:
```python
# In TUI connection flow
async def _connect_and_subscribe(self) -> None:
    """Connect to daemon and subscribe to thread."""
    await self.client.connect()

    # Get or create thread
    thread_id = await self._get_or_create_thread()

    # Subscribe with TUI verbosity preference
    # TUI typically uses 'normal' verbosity (user can adjust via config)
    verbosity = self.config.tui_verbosity if hasattr(self.config, "tui_verbosity") else "normal"
    await self.client.subscribe_thread(thread_id, verbosity=verbosity)

    logger.info("TUI subscribed to thread %s with verbosity=%s", thread_id, verbosity)
```

---

## File 7: `src/soothe/ux/cli/execution/daemon_runner.py`

### Changes

**7.1 Update subscription based on CLI flags**:
```python
async def _run_with_daemon(self, text: str) -> None:
    """Run query with daemon backend."""
    # Connect and subscribe
    await self.client.connect()

    # Determine verbosity from CLI flags
    verbosity = self._determine_verbosity()

    # Create or resume thread
    thread_id = await self._get_thread_id()
    await self.client.subscribe_thread(thread_id, verbosity=verbosity)

    # Send input
    await self.client.send_input(text)

    # Process events
    await self._process_events()


def _determine_verbosity(self) -> VerbosityLevel:
    """Determine verbosity from CLI flags.

    Returns:
        Verbosity level based on --verbose, --quiet, --debug flags
    """
    if hasattr(self, "debug") and self.debug:
        return "debug"
    if hasattr(self, "verbose") and self.verbose:
        return "detailed"
    if hasattr(self, "quiet") and self.quiet:
        return "minimal"
    return "normal"
```

---

## File 8: WebSocket Client Examples

### Changes

**8.1 Update example client**:
```javascript
// WebSocket client example
const ws = new WebSocket('ws://localhost:8765');

ws.onopen = () => {
    // Send subscription with verbosity
    ws.send(JSON.stringify({
        type: 'subscribe_thread',
        thread_id: 'my-thread-id',
        verbosity: 'normal'  // NEW: specify verbosity
    }));
};

ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);

    if (msg.type === 'subscription_confirmed') {
        console.log('Subscribed with verbosity:', msg.verbosity);
    }

    // Process events (filtered by daemon)
    if (msg.type === 'event') {
        console.log('Received event:', msg);
    }
};
```

---

## File 9: Verification Script

### Run Full Verification

```bash
./scripts/verify_finally.sh
```

**Expected Output**:
- Code formatting: ✅ Pass
- Linting (ruff): ✅ Zero errors
- Unit tests: ✅ 900+ tests pass
- Integration tests: ✅ All pass

**If Failures**:
1. Fix linting errors: `make lint`
2. Fix formatting: `make format`
3. Fix tests: Investigate and fix failing tests
4. Re-run verification

---

## Testing Checklist

### Unit Tests

- [ ] `test_client_session.py` - Verbosity field, subscribe_thread with verbosity
- [ ] `test_event_bus.py` - Publish with metadata, tuple format
- [ ] `test_handlers.py` - handle_subscribe_thread with verbosity, validation
- [ ] `test_filtering.py` - Filtering logic for all verbosity levels
- [ ] `test_backward_compat.py` - Old clients without verbosity field

### Integration Tests

- [ ] Multiple clients with different verbosity levels
- [ ] Event filtering for each verbosity category
- [ ] Event metadata propagation end-to-end
- [ ] Performance benchmarks (event reduction ratios)

### Manual Testing

- [ ] TUI connection with verbosity preference
- [ ] CLI headless with `--verbose`, `--quiet`, `--debug` flags
- [ ] WebSocket client with verbosity parameter
- [ ] Old client (no verbosity) still works

---

## Performance Metrics

### Metrics to Collect

**Implementation should add metrics**:
```python
# In client_session.py _sender_loop()
filtered_count = 0
delivered_count = 0

# When filtering
if not should_show(event_meta.verbosity, session.verbosity):
    filtered_count += 1
    continue

# When delivering
delivered_count += 1

# Log periodically
logger.info(
    "Client %s: filtered=%d, delivered=%d, ratio=%.1f%%",
    session.client_id,
    filtered_count,
    delivered_count,
    (filtered_count / (filtered_count + delivered_count)) * 100,
)
```

### Expected Performance

**Verbosity 'normal'**:
- Events filtered: 60-70%
- Bandwidth saved: 60-70%
- Client processing reduced: 60-70%

**Verbosity 'minimal'**:
- Events filtered: 90%
- Bandwidth saved: 90%

**Verbosity 'detailed'**:
- Events filtered: 30-40%
- Bandwidth saved: 30-40%

**Verbosity 'debug'**:
- Events filtered: 0% (all events sent)
- Still applies filtering logic (no passthrough)

---

## Rollback Plan

If issues arise, rollback is straightforward:

1. **Revert daemon changes**: Clients default to verbosity='normal' (same as current behavior)
2. **Revert event emission sites**: EventBus accepts None for event_meta (backward compatible)
3. **Revert client changes**: Clients can omit verbosity parameter (defaults to 'normal')

No breaking changes required for rollback.

---

## Documentation Updates

After implementation:

1. **Update RFC-400 reference**: Add verbosity field to protocol documentation
2. **Update client migration guide**: Document new verbosity parameter
3. **Update API documentation**: Document subscribe_thread verbosity parameter
4. **Update TUI/CLI help**: Document verbosity preferences

---

## Completion Checklist

- [ ] All daemon infrastructure implemented (Files 1-3)
- [ ] All event emission sites updated (Files 4)
- [ ] All clients updated (Files 5-8)
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Manual testing complete
- [ ] Performance metrics validated
- [ ] Documentation updated
- [ ] RFC-401 status changed to "Implemented"
- [ ] IG-081 status changed to "Completed"

---

**Implementation Timeline**: 3 weeks
**Expected Outcome**: 60-70% reduction in event transfer, improved performance