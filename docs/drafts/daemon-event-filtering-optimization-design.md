# Design Draft: Daemon-Side Event Filtering Optimization

**Created**: 2026-03-28
**Status**: Draft
**Kind**: Conceptual Design
**Goal**: Optimize Progress Event performance by filtering events at daemon side instead of client side

---

## Problem Analysis

### Current Architecture

**Event Flow (RFC-400)**:
```
Backend Events → EventBus.publish(topic) → ClientSession.event_queue → sender_loop → Transport → Client
```

**Client-Side Filtering (RFC-400)**:
- Clients subscribe to threads via `subscribe_thread` message
- All backend events are emitted to subscribed clients
- Clients use `DisplayPolicy` + `EventProcessor` to filter events based on verbosity
- Verbosity levels: minimal, normal, detailed, debug

**Key Components**:
- `EventBus`: Pub/sub with topic-based routing (`thread:{thread_id}`)
- `ClientSessionManager`: Manages sessions, subscriptions, event delivery
- `ClientSession`: Per-client state (event_queue maxsize=100, sender_task)
- `DisplayPolicy`: Client-side event filtering logic (`should_show_event()`)
- `EventProcessor`: Client-side event processing and rendering

### Performance Problem

**Current Overhead**:
1. Daemon emits **ALL** events to subscribed clients (70+ event types)
2. Clients receive events via transport (network/socket serialization)
3. Clients parse JSON events
4. Clients filter events using `DisplayPolicy.should_show_event()`
5. Large percentage of events are **filtered out and discarded**

**Example Scenario**:
- Backend emits 100 events during agent execution
- Client at "normal" verbosity receives ALL 100 events
- `DisplayPolicy` filters out 70 events (only 30 shown)
- **70% of events transferred unnecessarily**

**Wasted Resources**:
- Network bandwidth (Unix socket, WebSocket)
- Serialization/deserialization overhead
- Client-side processing (JSON parsing, filtering logic)
- Event queue memory (maxsize=100)

### Root Cause

**No Client Preference Propagation**:
- Daemon has **no knowledge** of client verbosity preferences
- Subscription protocol (RFC-400) only includes `thread_id`
- Clients cannot specify filtering preferences during subscription
- Filtering logic exists only at client side (`DisplayPolicy`)

---

## Design Goals

### Primary Goals

1. **Reduce network overhead**: Filter events at daemon before transport
2. **Maintain backward compatibility**: Existing clients continue working
3. **Preserve client autonomy**: Clients control their verbosity preferences
4. **Minimal protocol changes**: Extend subscription message, not redesign protocol

### Secondary Goals

5. **Performance measurable**: Metrics for filtering efficiency
6. **Extensible design**: Support future filtering criteria (event types, domains)
7. **No client-side complexity increase**: Keep `DisplayPolicy` as fallback/secondary filter

### Non-Goals

- **Not replacing client filtering**: Client-side `DisplayPolicy` remains for edge cases
- **Not changing event taxonomy**: RFC-400 event classification unchanged
- **Not implementing complex query language**: Simple verbosity-based filtering only

---

## Design Exploration: Three Approaches

### Approach 1: Verbosity-Based Subscription Filtering

**Concept**: Clients specify verbosity preference in `subscribe_thread` message

**Protocol Extension**:
```json
{
  "type": "subscribe_thread",
  "thread_id": "string (required)",
  "verbosity": "string (optional, default: 'normal')"
}
```

**Verbosity Values**: minimal, normal, detailed, debug

**Implementation**:
- Add `verbosity` field to `ClientSession` (per-client preference)
- Modify `EventBus.publish()` to accept event metadata (verbosity classification)
- Filter events at `ClientSessionManager._sender_loop()` before enqueueing
- Use RFC-400 `EventRegistry.get_verbosity()` to classify events

**Event Filtering Logic**:
```python
# In ClientSessionManager
async def _filter_and_enqueue(self, session: ClientSession, event: dict) -> bool:
    """Filter event based on client verbosity preference.

    Returns:
        True if event should be enqueued, False if filtered out
    """
    etype = event.get("type", "")
    event_verbosity = self._event_registry.get_verbosity(etype)

    # Use RFC-400 should_show logic
    if not should_show(event_verbosity, session.verbosity):
        return False  # Filter out

    # Enqueue filtered event
    await session.event_queue.put(event)
    return True
```

**Pros**:
- ✅ Minimal protocol change (add optional field)
- ✅ Backward compatible (default verbosity='normal')
- ✅ Clear semantics (verbosity maps to RFC-400 categories)
- ✅ Easy to implement (reuse RFC-400 logic)
- ✅ Significant performance gain (70% reduction estimated)

**Cons**:
- ❌ Single verbosity per client (cannot vary per thread)
- ❌ Requires verbosity classification for ALL events (must be complete)
- ❌ Client cannot dynamically change verbosity (requires re-subscription)

**Compatibility Strategy**:
- Old clients: omit `verbosity` → default to 'normal'
- New clients: specify `verbosity` → daemon-side filtering
- Hybrid: daemon filters by verbosity, client applies additional filters

---

### Approach 2: Event-Type Whitelist/Blacklist Filtering

**Concept**: Clients specify which event types to receive via whitelist/blacklist

**Protocol Extension**:
```json
{
  "type": "subscribe_thread",
  "thread_id": "string (required)",
  "event_filter": {
    "mode": "whitelist|blacklist",
    "event_types": ["soothe.protocol.*", "soothe.error.*"]
  }
}
```

**Implementation**:
- Add `event_filter` field to `ClientSession`
- Pattern matching: `soothe.protocol.*` matches all protocol events
- Filter at `_sender_loop()` using pattern match

**Pros**:
- ✅ Flexible (clients choose specific event types)
- ✅ Fine-grained control (per-event filtering)
- ✅ Extensible (future: domain filtering, regex patterns)

**Cons**:
- ❌ Complex protocol (event_filter object with mode + patterns)
- ❌ Client burden (clients must know event taxonomy)
- ❌ Pattern matching overhead (O(n) pattern checks per event)
- ❌ Not backward compatible (defaults unclear)

**Rejected**: Too complex for primary use case (verbosity filtering)

---

### Approach 3: Two-Stage Filtering (Daemon + Client)

**Concept**: Daemon performs coarse filtering (domain-based), client performs fine filtering

**Protocol Extension**:
```json
{
  "type": "subscribe_thread",
  "thread_id": "string (required)",
  "domains": ["protocol", "output", "error"]  // Receive these domains only
}
```

**Implementation**:
- Client specifies domains to receive (lifecycle, protocol, tool, subagent, output, error)
- Daemon filters by domain (second segment of event type)
- Client applies `DisplayPolicy` for fine-grained filtering

**Event Flow**:
```
Backend Event → EventBus → Domain Filter (daemon) → Transport → Client → DisplayPolicy Filter → Display
```

**Pros**:
- ✅ Coarse filtering at daemon (domain-based)
- ✅ Simple protocol (list of domains)
- ✅ Backward compatible (default: all domains)
- ✅ Structural classification (RFC-400 domain taxonomy)

**Cons**:
- ❌ Still transfers unwanted events within domain (e.g., debug-level protocol events)
- ❌ Client must still apply `DisplayPolicy` (redundant filtering)
- ❌ Less performance gain than Approach 1

**Hybrid Strategy**: Combine with Approach 1 for maximum efficiency

---

## Recommended Solution: Approach 1 + Enhancements

### Core Design: Verbosity-Based Filtering

**Protocol Extension**:
```json
{
  "type": "subscribe_thread",
  "thread_id": "abc123",
  "verbosity": "normal"  // NEW: optional, default='normal'
}
```

**Default Verbosity**: 'normal' (backward compatible with existing clients)

**Event Classification**:
- Use RFC-400 `EventRegistry.get_verbosity(event_type)` to map events to verbosity categories
- Categories: assistant_text, protocol, tool_activity, subagent_progress, subagent_custom, error
- Map verbosity levels to categories via `should_show(category, verbosity)` (RFC-400)

**Implementation Changes**:

1. **Protocol Layer** (`RFC-400`):
   - Extend `subscribe_thread` message schema with optional `verbosity` field
   - Add `verbosity` field to `ClientSession` dataclass
   - Default: `verbosity='normal'` for backward compatibility

2. **ClientSessionManager** (`client_session.py`):
   ```python
   async def subscribe_thread(self, client_id: str, thread_id: str, verbosity: VerbosityLevel = "normal") -> None:
       """Subscribe with verbosity preference."""
       session = await self.get_session(client_id)
       if session:
           session.verbosity = verbosity
           topic = f"thread:{thread_id}"
           await self._event_bus.subscribe(topic, session.event_queue)
           session.subscriptions.add(thread_id)
   ```

3. **EventBus Enhancement** (`event_bus.py`):
   ```python
   async def publish(self, topic: str, event: dict[str, Any], event_meta: EventMeta | None = None) -> None:
       """Publish with optional metadata for filtering."""
       # Pass metadata to queues for filtering decisions
       for queue in queues:
           queue.put_nowait((event, event_meta))  # Tuple: (event, metadata)
   ```

4. **Sender Loop Filtering** (`client_session.py`):
   ```python
   async def _sender_loop(self, session: ClientSession) -> None:
       """Send events with daemon-side filtering."""
       while True:
           event, event_meta = await session.event_queue.get()

           # Daemon-side filtering
           if event_meta and not should_show(event_meta.verbosity, session.verbosity):
               logger.debug("Filtered event %s for client %s", event.get("type"), session.client_id)
               continue  # Skip event

           # Send filtered event
           await session.transport.send(session.transport_client, event)
   ```

5. **Event Metadata Injection** (`core/runner.py`):
   ```python
   # When emitting events
   event_meta = REGISTRY.get_meta(event_type)
   await self._event_bus.publish(topic, event, event_meta=event_meta)
   ```

### Enhanced Features

#### Feature 1: Dynamic Verbosity Change

**Protocol Extension**:
```json
{
  "type": "change_verbosity",
  "verbosity": "detailed"
}
```

**Implementation**:
- Add `change_verbosity` message handler
- Update `ClientSession.verbosity` dynamically
- No re-subscription required

**Use Case**: TUI toggle verbosity without disconnecting

#### Feature 2: Per-Thread Verbosity

**Protocol Extension**:
```json
{
  "type": "subscribe_thread",
  "thread_id": "abc123",
  "verbosity": "normal"
}

{
  "type": "subscribe_thread",
  "thread_id": "xyz789",
  "verbosity": "debug"
}
```

**Implementation**:
- Change `ClientSession.verbosity` to `dict[str, VerbosityLevel]` (thread_id → verbosity)
- Filter based on thread-specific verbosity

**Use Case**: Monitor multiple threads with different verbosity levels

#### Feature 3: Client-Side Override

**Concept**: Client can request ALL events (verbosity='debug') and apply custom filtering

**Implementation**:
- Client subscribes with `verbosity='debug'` (receive all events)
- Client applies custom `DisplayPolicy` logic for specialized filtering
- Daemon acts as "passthrough" for debug verbosity

**Use Case**: Custom client implementations (web UI, analytics, debugging)

---

## Implementation Plan

### Phase 1: Core Filtering (Week 1)

**Goal**: Implement verbosity-based subscription filtering

**Tasks**:
1. Extend `subscribe_thread` message schema (RFC-400 update)
2. Add `verbosity` field to `ClientSession`
3. Modify `ClientSessionManager.subscribe_thread()` to accept verbosity
4. Enhance `EventBus.publish()` to pass event metadata
5. Implement filtering logic in `_sender_loop()`
6. Update `Subscription Confirmed` message to echo verbosity

**Testing**:
- Unit tests: filtering logic for all verbosity levels
- Integration tests: subscribe with verbosity, verify filtered events
- Performance tests: measure event reduction ratio

### Phase 2: Dynamic Verbosity (Week 2)

**Goal**: Add `change_verbosity` message for dynamic updates

**Tasks**:
1. Add `change_verbosity` message schema
2. Implement handler in `_handlers.py`
3. Update `ClientSession.verbosity` dynamically
4. Test verbosity changes during active event stream

### Phase 3: Metrics & Observability (Week 3)

**Goal**: Measure filtering efficiency

**Tasks**:
1. Add metrics: events_filtered_total, events_delivered_total
2. Log filtering decisions (debug level)
3. Dashboard: filtering ratio per client, per thread
4. Performance report: bandwidth saved, CPU reduction

### Phase 4: Client Updates (Week 4)

**Goal**: Update clients to use daemon-side filtering

**Tasks**:
1. Update `client.py` to support `subscribe_thread(verbosity=...)`
2. Update TUI app to specify verbosity preference
3. Update CLI headless to specify verbosity based on `--verbose` flag
4. Update WebSocket client examples
5. Documentation: migration guide, protocol extension

### Phase 5: Advanced Features (Week 5)

**Goal**: Per-thread verbosity, client override, hybrid filtering

**Tasks**:
1. Implement per-thread verbosity (thread-specific preferences)
2. Test client override scenarios (verbosity='debug' + custom DisplayPolicy)
3. Hybrid filtering validation (daemon + client both filtering)

---

## Performance Estimates

### Current State (No Filtering)

**Event Transfer Ratio**: 100% (all events transferred)

**Example**: 100 backend events → 100 events to client → 30 displayed (70 filtered out)

### Projected State (Verbosity Filtering)

**Event Transfer Ratio**: ~30-40% (estimated reduction)

**Example**: 100 backend events → 30-40 events to client → 30 displayed (minimal client filtering)

**Performance Gain**:
- Network bandwidth: **60-70% reduction**
- Serialization overhead: **60-70% reduction**
- Client-side processing: **60-70% reduction**
- Event queue memory: **60-70% reduction**

### Metrics to Collect

- `events_emitted_total`: Backend events generated
- `events_filtered_total`: Events filtered at daemon
- `events_delivered_total`: Events sent to clients
- `filtering_ratio`: events_filtered / events_emitted
- `bandwidth_saved_bytes`: Estimated bytes saved

---

## Compatibility Analysis

### Backward Compatibility

**Old Clients** (no verbosity field):
- Daemon defaults to `verbosity='normal'`
- Behavior unchanged from current state
- No breaking changes

**New Clients** (specify verbosity):
- Daemon applies filtering
- Reduced event transfer
- Better performance

### Forward Compatibility

**Protocol Extension**:
- Optional field (defaults handled)
- Extensible design (future: per-thread verbosity, custom filters)
- Message schema unchanged except new optional field

### Migration Strategy

**Gradual Rollout**:
1. Deploy daemon with filtering support
2. Old clients continue working (default verbosity)
3. New clients opt-in by specifying verbosity
4. No hard migration required

**Client Update Timeline**:
- TUI: Week 4 (after daemon deployment)
- CLI: Week 4 (with `--verbose` flag support)
- WebSocket: Week 4 (examples updated)

---

## Alternative Considerations

### Why Not Filter at EventBus?

**Considered**: Filter events at `EventBus.publish()` before routing to queues

**Rejected**:
- EventBus is routing layer, not filtering layer
- Requires EventBus to know client preferences (breaks separation of concerns)
- EventBus cannot filter per-client (different clients have different verbosity)
- Better: Filter at `ClientSessionManager._sender_loop()` (per-client, late-stage)

### Why Not Remove Client Filtering?

**Considered**: Remove `DisplayPolicy` after daemon filtering

**Rejected**:
- Client filtering remains for edge cases (custom logic beyond verbosity)
- Hybrid filtering safer (daemon coarse, client fine)
- Client autonomy preserved (client controls final display)

### Why Not Use Event-Type Blacklist?

**Considered**: Clients blacklist unwanted event types

**Rejected**:
- Too complex for primary use case
- Client burden (must know taxonomy)
- Verbosity simpler and aligns with RFC-400

---

## Risks & Mitigations

### Risk 1: Incomplete Verbosity Classification

**Risk**: Some events not classified in `EventRegistry`

**Mitigation**:
- RFC-400 ensures all events classified
- Fallback: unclassified events default to 'protocol' category
- Test coverage: verify classification completeness

### Risk 2: Client Verbosity Mismatch

**Risk**: Client and daemon verbosity semantics differ

**Mitigation**:
- Use RFC-400 `should_show()` logic at both sides
- Shared classification logic (same function)
- Test alignment: verify daemon/client filtering match

### Risk 3: Performance Overhead of Filtering

**Risk**: Filtering logic adds CPU overhead

**Mitigation**:
- O(1) classification (EventRegistry lookup)
- Filter at late stage (sender_loop, not publish)
- Profile performance: ensure net gain positive

### Risk 4: Backward Compatibility Break

**Risk**: Protocol change breaks old clients

**Mitigation**:
- Optional field with default
- Old clients omit verbosity → default='normal'
- Integration tests: old client compatibility

---

## Decision Summary

### Recommended: Approach 1 (Verbosity-Based Filtering)

**Rationale**:
- ✅ Minimal protocol change
- ✅ Backward compatible
- ✅ Clear semantics (verbosity categories)
- ✅ Significant performance gain (60-70% reduction)
- ✅ Easy to implement (reuse RFC-400 logic)

**Enhancements**:
- Dynamic verbosity change (Week 2)
- Per-thread verbosity (Week 5)
- Metrics & observability (Week 3)

**Implementation Timeline**: 5 weeks (phased rollout)

**Expected Outcome**:
- 60-70% reduction in event transfer
- Maintained backward compatibility
- Improved client performance
- Foundation for future filtering features

---

## Open Questions

1. **Per-Thread vs Per-Client Verbosity**: Should verbosity be per-thread (different verbosity for different threads) or per-client (single verbosity for all subscribed threads)?
   - **Recommendation**: Start with per-client (simple), add per-thread in Phase 5 (advanced)

2. **Verbosity Change Frequency**: Should clients be able to change verbosity frequently (during event stream) or only at subscription?
   - **Recommendation**: Support dynamic change via `change_verbosity` message (Phase 2)

3. **Client Override for Debug**: Should `verbosity='debug'` mean "passthrough all events" (no daemon filtering)?
   - **Recommendation**: Yes, daemon passes all events for debug, client applies custom filtering

4. **Event Metadata Size**: Passing `EventMeta` through queues increases memory. Should we pass only verbosity field?
   - **Recommendation**: Pass minimal metadata (verbosity category only), not full EventMeta

5. **Filtering Location**: Filter at EventBus.publish() (early) or sender_loop (late)?
   - **Recommendation**: Filter at sender_loop (late-stage, per-client, preserves EventBus routing role)

---

## Next Steps

1. **Review & Approval**: Present design to user for feedback
2. **RFC Draft**: Create RFC-XXXX (Event Filtering Protocol) if approved
3. **Implementation Guide**: Create IG-XXX implementation guide
4. **Phase 1 Implementation**: Start core filtering implementation (Week 1)

---

**Status**: Draft ready for review