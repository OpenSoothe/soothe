# RFC-0022: Daemon-Side Event Filtering Protocol

**RFC**: 0022
**Title**: Daemon-Side Event Filtering Protocol
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-03-28
**Updated**: 2026-03-28
**Dependencies**: RFC-0013, RFC-0015, RFC-0024

## Abstract

This RFC extends RFC-0013's subscription protocol to support daemon-side event filtering based on client verbosity preferences. By filtering events at the daemon before transport, we reduce network bandwidth, serialization overhead, and client-side processing by an estimated 60-70%. The design maintains backward compatibility through optional protocol fields and preserves client autonomy through client-side `DisplayPolicy` as a secondary filter.

## Motivation

### Problem: Performance Overhead from Client-Side Filtering

RFC-0015 defines a comprehensive progress event protocol with 70+ event types across six domains (lifecycle, protocol, tool, subagent, output, error). RFC-0013's event bus architecture ensures client isolation by routing events only to subscribed clients. However, **all subscribed events are delivered regardless of client verbosity preferences**.

**Current Event Flow**:
```
Backend → EventBus.publish() → ClientSession.event_queue → Transport → Client → DisplayPolicy.filter() → Display
```

**Performance Impact**:
- Backend emits 100 events during agent execution
- Client subscribes to thread with 'normal' verbosity
- All 100 events transferred to client
- Client-side `DisplayPolicy.should_show_event()` filters out 70 events (only 30 displayed)
- **70% of events transferred unnecessarily**

**Wasted Resources**:
1. Network bandwidth (Unix socket, WebSocket serialization)
2. CPU overhead (JSON serialization/deserialization)
3. Memory overhead (event queues with maxsize=100)
4. Client-side processing (parsing, filtering logic)

### Root Cause: No Client Preference Propagation

The daemon has **no knowledge** of client verbosity preferences. RFC-0013's `subscribe_thread` message only specifies `thread_id`, with no mechanism for clients to communicate filtering preferences. Filtering logic exists exclusively at client side (`DisplayPolicy`, RFC-0019), causing the daemon to deliver all events.

### Design Goals

1. **Reduce network overhead**: Filter events at daemon before transport (60-70% reduction)
2. **Maintain backward compatibility**: Existing clients continue working unchanged
3. **Preserve client autonomy**: Client-side `DisplayPolicy` remains for edge cases
4. **Minimal protocol changes**: Extend subscription message, not redesign protocol
5. **Reuse existing classification**: Leverage RFC-0015's `EventRegistry` for event categorization

### Non-Goals

- **Dynamic verbosity changes**: Verbosity fixed at subscription time
- **Per-thread verbosity**: Verbosity applies to all threads for a client
- **Passthrough modes**: No special "send all events" mode for any verbosity level
- **Replacing client filtering**: `DisplayPolicy` remains as secondary/fallback filter

## Guiding Principles

### Principle 1: Filter Late, Filter Per-Client

Event filtering occurs at the **latest possible stage** (sender_loop) to preserve EventBus routing simplicity. Filtering is **per-client** to support different clients having different verbosity preferences.

### Principle 2: Reuse RFC-0024 VerbosityTier

Use RFC-0024's unified `VerbosityTier` enum for event classification. No new categorization logic introduced. Verbosity tiers (`QUIET`, `NORMAL`, `DETAILED`, `DEBUG`, `INTERNAL`) map directly to RFC-0024's definitions. Visibility is determined by integer comparison: `tier <= verbosity`.

### Principle 3: Backward Compatibility via Defaults

Protocol extension uses **optional fields with defaults**. Old clients omitting verbosity receive default behavior (verbosity='normal'), identical to current state. No breaking changes.

### Principle 4: Client-Side Filtering Remains

Daemon filtering is **coarse-grained** (verbosity-based). Client-side `DisplayPolicy` provides **fine-grained** filtering for edge cases. Hybrid approach: daemon reduces volume, client handles specifics.

## Architecture

### Event Classification Mapping

RFC-0024 defines five VerbosityTier values mapped to domain defaults:

| Domain | Default VerbosityTier | Visible at Verbosity Levels |
|--------|----------------------|-----------------------------|
| `lifecycle` | DETAILED (2) | detailed, debug |
| `protocol` | DETAILED (2) | detailed, debug |
| `tool` | DETAILED (2) | detailed, debug |
| `subagent` | DETAILED (2) | detailed, debug (promoted: NORMAL at normal) |
| `output` | QUIET (0) | quiet, normal, detailed, debug |
| `error` | QUIET (0) | always shown |

**Visibility Function** (from RFC-0024):
```python
def should_show(tier: VerbosityTier, verbosity: VerbosityLevel) -> bool:
    """Check if tier should be shown at given verbosity via integer comparison."""
    if tier == VerbosityTier.INTERNAL:
        return False  # Never show internal events
    return tier <= _VERBOSITY_LEVEL_VALUES[verbosity]  # Integer comparison
```

**VerbosityLevel Mapping**:
```python
_VERBOSITY_LEVEL_VALUES: dict[VerbosityLevel, int] = {
    "quiet": 0,     # Shows QUIET (0) only
    "normal": 1,    # Shows QUIET (0) + NORMAL (1)
    "detailed": 2,  # Shows QUIET (0) + NORMAL (1) + DETAILED (2)
    "debug": 3,     # Shows QUIET (0) + NORMAL (1) + DETAILED (2) + DEBUG (3)
}
```

### Protocol Extension

**Extended `subscribe_thread` Message**:
```json
{
  "type": "subscribe_thread",
  "thread_id": "string (required)",
  "verbosity": "string (optional, values: quiet|normal|detailed|debug, default: normal)"
}
```

**Default Behavior**: Clients omitting `verbosity` receive default value `'normal'`, matching current client-side filtering expectations.

**Extended `subscription_confirmed` Message**:
```json
{
  "type": "subscription_confirmed",
  "thread_id": "string (required)",
  "client_id": "string (required)",
  "verbosity": "string (required, echoes client preference or default)"
}
```

Echoes verbosity to client for confirmation.

### Data Model Changes

**ClientSession Extension** (RFC-0013):
```python
@dataclass
class ClientSession:
    client_id: str
    transport: TransportServer
    transport_client: Any
    subscriptions: set[str] = field(default_factory=set)
    event_queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(maxsize=100))
    sender_task: asyncio.Task[None] | None = None
    verbosity: VerbosityLevel = "normal"  # NEW: client verbosity preference
```

**VerbosityLevel Type** (from RFC-0024):
```python
VerbosityLevel = Literal["quiet", "normal", "detailed", "debug"]
```

### Event Filtering Flow

**Before (Current)**:
```
Backend Event → EventBus.publish(topic, event) →
  ClientSession.event_queue.put(event) →
    sender_loop → Transport.send(event) →
      Client → DisplayPolicy.filter(event)
```

**After (Proposed)**:
```
Backend Event → EventBus.publish(topic, event, event_meta) →
  ClientSessionManager._filter_and_enqueue(session, event, event_meta) →
    [Filter Check: should_show(event_meta.verbosity, session.verbosity)] →
      [PASS] event_queue.put(event) → sender_loop → Transport.send(event) → Client
      [FAIL] Drop event, log filtered count
```

### Event Metadata Propagation

**EventBus.publish Enhancement**:
```python
class EventBus:
    async def publish(
        self,
        topic: str,
        event: dict[str, Any],
        event_meta: EventMeta | None = None  # NEW: optional metadata
    ) -> None:
        """Publish event with optional metadata for filtering."""
        async with self._lock:
            queues = self._subscribers.get(topic, set()).copy()

        if not queues:
            return

        # Pass metadata to queues for filtering decisions
        for queue in queues:
            queue.put_nowait((event, event_meta))  # NEW: tuple (event, metadata)
```

**EventMeta Structure** (from RFC-0015, updated by RFC-0024):
```python
@dataclass(frozen=True)
class EventMeta:
    """Metadata for event filtering and display."""
    type_string: str
    verbosity: VerbosityTier  # Unified visibility tier (RFC-0024)
    # ... other fields (domain, component, action, summary_template)
```

### Filtering Implementation

**ClientSessionManager._sender_loop Filtering**:
```python
async def _sender_loop(self, session: ClientSession) -> None:
    """Send events from queue with daemon-side filtering."""
    try:
        while True:
            # Get event with metadata (tuple)
            event_data = await session.event_queue.get()

            # Extract event and metadata
            if isinstance(event_data, tuple):
                event, event_meta = event_data
            else:
                # Backward compatibility: legacy events without metadata
                event = event_data
                event_meta = None

            # Daemon-side filtering
            if event_meta:
                # Use RFC-0024's should_show logic (integer comparison)
                from soothe.ux.core.verbosity_tier import should_show

                if not should_show(event_meta.verbosity, session.verbosity):
                    # Filter out - do not send to client
                    logger.debug(
                        "Filtered event %s for client %s (verbosity=%s, client=%s)",
                        event.get("type"),
                        session.client_id,
                        event_meta.verbosity,
                        session.verbosity,
                    )
                    continue  # Skip event

            # Send filtered event to client
            try:
                await session.transport.send(session.transport_client, event)
            except Exception:
                logger.exception("Failed to send event to client %s", session.client_id)
                break

    except asyncio.CancelledError:
        logger.debug("Sender task cancelled for client %s", session.client_id)
        raise
```

**Key Points**:
1. Events received as `(event, event_meta)` tuples from EventBus
2. Filtering uses RFC-0015's `should_show(event_meta.verbosity, session.verbosity)`
3. Filtered events **never reach transport layer** (maximum performance gain)
4. Backward compatibility: legacy events without metadata are sent unfiltered

### Event Emission Changes

**Backend Event Emission** (e.g., SootheRunner):
```python
# Before (current)
await self._event_bus.publish(topic, event_dict)

# After (proposed)
from soothe.core.event_catalog import REGISTRY

event_type = event_dict.get("type", "")
event_meta = REGISTRY.get_meta(event_type)
await self._event_bus.publish(topic, event_dict, event_meta=event_meta)
```

**Changes Required**:
- All event emission sites must pass `event_meta` from `REGISTRY.get_meta()`
- Ensures every event has classification metadata for filtering

## Implementation Requirements

### Requirement 1: Protocol Handler Extension

**File**: `src/soothe/daemon/_handlers.py`

**Handler Modification**:
```python
async def handle_subscribe_thread(self, client_id: str, message: dict[str, Any]) -> None:
    """Handle subscribe_thread message with optional verbosity."""
    thread_id = message.get("thread_id", "")
    verbosity = message.get("verbosity", "normal")  # NEW: optional, default='normal'

    if not thread_id:
        await self._send_error(client_id, "INVALID_MESSAGE", "Missing thread_id")
        return

    # Validate verbosity
    valid_verbosity = {"quiet", "normal", "detailed", "debug"}
    if verbosity not in valid_verbosity:
        await self._send_error(client_id, "INVALID_MESSAGE", f"Invalid verbosity: {verbosity}")
        return

    # Subscribe with verbosity
    await self._session_manager.subscribe_thread(client_id, thread_id, verbosity=verbosity)

    # Send confirmation with echoed verbosity
    await self._send_message(client_id, {
        "type": "subscription_confirmed",
        "thread_id": thread_id,
        "client_id": client_id,
        "verbosity": verbosity,  # NEW: echo verbosity
    })
```

### Requirement 2: ClientSessionManager Extension

**File**: `src/soothe/daemon/client_session.py`

**subscribe_thread Method**:
```python
async def subscribe_thread(
    self,
    client_id: str,
    thread_id: str,
    verbosity: VerbosityLevel = "normal"  # NEW: verbosity parameter
) -> None:
    """Subscribe client to thread with verbosity preference.

    Args:
        client_id: Client identifier
        thread_id: Thread identifier
        verbosity: Verbosity preference (quiet|normal|detailed|debug)

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

**ClientSession Dataclass**: Add `verbosity: VerbosityLevel = "normal"` field

### Requirement 3: EventBus Enhancement

**File**: `src/soothe/daemon/event_bus.py`

**publish Method**:
```python
async def publish(
    self,
    topic: str,
    event: dict[str, Any],
    event_meta: EventMeta | None = None  # NEW: optional metadata
) -> None:
    """Publish event to all subscribers with optional metadata.

    Args:
        topic: Topic identifier (e.g., "thread:abc123")
        event: Event dictionary
        event_meta: Optional EventMeta for filtering
    """
    async with self._lock:
        queues = self._subscribers.get(topic, set()).copy()

    if not queues:
        logger.debug("No subscribers for topic %s", topic)
        return

    # Send (event, event_meta) tuple to queues
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

### Requirement 4: Sender Loop Filtering

**File**: `src/soothe/daemon/client_session.py`

**_sender_loop Method**: Implement filtering logic (see detailed code in Architecture section)

**Imports Required**:
```python
from soothe.core.event_catalog import EventMeta
from soothe.ux.core.verbosity_tier import should_show, VerbosityTier
```

### Requirement 5: Event Emission Sites

**All Backend Emission Sites**: Pass `event_meta` when publishing

**Files to Update**:
- `src/soothe/core/runner.py` (main event emission)
- `src/soothe/cognition/*.py` (goal, plan events)
- `src/soothe/backends/*/` (protocol events)
- `src/soothe/subagents/*/` (subagent events)
- `src/soothe/tools/*/` (tool events)

**Pattern**:
```python
from soothe.core.event_catalog import REGISTRY

event_type = event_dict.get("type")
event_meta = REGISTRY.get_meta(event_type) if event_type else None
await event_bus.publish(topic, event_dict, event_meta=event_meta)
```

### Requirement 6: Client Updates

**Files to Update**:
- `src/soothe/daemon/client.py` (client library)
- `src/soothe/ux/tui/app.py` (TUI client)
- `src/soothe/ux/cli/execution/daemon_runner.py` (CLI headless)
- WebSocket client examples

**Pattern**:
```python
# Client library (client.py)
async def subscribe_thread(
    self,
    thread_id: str,
    verbosity: VerbosityLevel = "normal"  # NEW: verbosity parameter
) -> None:
    """Subscribe to thread with verbosity preference."""
    await self._send({
        "type": "subscribe_thread",
        "thread_id": thread_id,
        "verbosity": verbosity,  # NEW: include verbosity
    })

    # Wait for subscription_confirmed echoing verbosity
    response = await self._receive()
    if response.get("type") != "subscription_confirmed":
        raise ProtocolError("Expected subscription_confirmed")

    echoed_verbosity = response.get("verbosity")
    if echoed_verbosity != verbosity:
        logger.warning("Verbosity mismatch: requested=%s, received=%s", verbosity, echoed_verbosity)
```

## Performance Expectations

### Event Reduction Ratios

**Estimated by Verbosity**:
- `quiet`: ~90% reduction (only QUIET tier events: errors, assistant text, final reports)
- `normal`: ~60-70% reduction (QUIET + NORMAL tier events)
- `detailed`: ~30-40% reduction (QUIET + NORMAL + DETAILED tier events)
- `debug`: ~0% reduction (all events sent except INTERNAL tier)

**Note**: Debug mode still applies filtering logic (no passthrough), ensuring consistent behavior.

### Resource Savings

**Network Bandwidth**:
- Current: ~1.5KB per event (JSON serialization)
- Estimated savings: 60-70% reduction = ~0.9-1.0KB saved per event

**Serialization Overhead**:
- JSON encoding/decoding CPU cycles reduced proportionally

**Event Queue Memory**:
- Current: maxsize=100, frequently full during high event volume
- Reduced queue pressure: fewer events enqueued

**Client Processing**:
- Reduced JSON parsing, filtering logic execution

### Metrics to Collect

**Implementation should track**:
- `events_emitted_total`: Backend events generated
- `events_filtered_total`: Events filtered at daemon (per client, per verbosity)
- `events_delivered_total`: Events sent to clients
- `filtering_ratio`: events_filtered / events_emitted
- `bandwidth_saved_bytes`: Estimated bytes saved (events_filtered × average_event_size)

## Backward Compatibility

### Protocol Compatibility

**Old Clients** (no verbosity field):
- Send `{"type": "subscribe_thread", "thread_id": "abc123"}`
- Daemon defaults to `verbosity='normal'`
- Behavior identical to current (no breaking change)

**New Clients** (with verbosity):
- Send `{"type": "subscribe_thread", "thread_id": "abc123", "verbosity": "detailed"}`
- Daemon applies specified verbosity filtering
- Performance improvement for client

### Event Format Compatibility

**Event Tuples in Queues**:
- New format: `(event_dict, event_meta)`
- Legacy format: `event_dict` (no metadata)
- Sender loop handles both: `if isinstance(event_data, tuple): ... else: ...`
- Ensures backward compatibility during migration

### Client-Side Filtering Preservation

**Hybrid Approach**:
- Daemon filtering: coarse-grained (verbosity-based)
- Client filtering: fine-grained (DisplayPolicy edge cases)
- Example: Client at verbosity='normal' receives protocol events, but DisplayPolicy may filter specific protocol events based on custom logic

**Why Client Filtering Remains**:
- Custom filtering beyond verbosity (e.g., internal context tracking)
- Edge cases not covered by RFC-0015 classification
- Client autonomy for display decisions

## Migration Strategy

### Phase 1: Daemon Implementation (Week 1)

**Goal**: Implement daemon-side filtering infrastructure

**Tasks**:
1. Extend `ClientSession` with `verbosity` field
2. Modify `subscribe_thread()` to accept verbosity parameter
3. Enhance `EventBus.publish()` to pass event metadata
4. Implement filtering in `_sender_loop()`
5. Update `_handlers.py` to handle verbosity in subscribe_thread message

**Testing**:
- Unit tests: filtering logic for all verbosity levels
- Integration tests: subscribe with verbosity, verify filtered events
- Backward compatibility tests: old clients without verbosity field

### Phase 2: Event Emission Updates (Week 2)

**Goal**: Update all event emission sites to pass metadata

**Tasks**:
1. Identify all `EventBus.publish()` calls in codebase
2. Add `REGISTRY.get_meta()` lookup for event type
3. Pass `event_meta` to `publish()`
4. Verify metadata for all 70+ event types

**Testing**:
- Verify event metadata completeness
- Test filtering for each event category

### Phase 3: Client Updates (Week 3)

**Goal**: Update clients to specify verbosity preferences

**Tasks**:
1. Update `client.py` to support `subscribe_thread(verbosity=...)`
2. Update TUI app to specify verbosity based on user preference
3. Update CLI headless to specify verbosity based on `--verbose` flag
4. Update WebSocket client examples

**Testing**:
- Integration tests: clients with different verbosity levels
- Performance benchmarks: measure event reduction ratios

### Phase 4: Metrics & Documentation (Week 4)

**Goal**: Collect metrics and document protocol extension

**Tasks**:
1. Add filtering metrics (events_filtered, events_delivered)
2. Performance report: bandwidth saved, filtering ratios
3. Update RFC-0013 reference documentation
4. Update client migration guide

## Dependencies

- RFC-0013 (Unified Daemon Communication Protocol — subscription protocol)
- RFC-0015 (Progress Event Protocol — event classification)
- RFC-0024 (VerbosityTier Unification — unified verbosity classification)
- RFC-0019 (Unified Event Processing — client-side DisplayPolicy)

## Related Documents

- [RFC-0013](./RFC-0013-daemon-communication-protocol.md) — Daemon communication protocol
- [RFC-0015](./RFC-0015-progress-event-protocol.md) — Event classification system
- [RFC-0024](./RFC-0024-verbosity-tier-unification.md) — VerbosityTier unification
- [RFC-0019](./RFC-0019-unified-event-processing.md) — Event processing architecture
- [RFC Index](./rfc-index.md) — All RFCs

---

*This RFC extends RFC-0013's subscription protocol to support daemon-side event filtering, reducing network overhead by 60-70% while maintaining backward compatibility.*