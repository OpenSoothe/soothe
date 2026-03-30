# RFC-0022: Daemon-Side Event Filtering Protocol

**RFC**: 0022
**Title**: Daemon-Side Event Filtering Protocol
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-03-28
**Updated**: 2026-03-28
**Dependencies**: RFC-0013, RFC-0015, RFC-0024

## Abstract

This RFC extends RFC-0013's subscription protocol to support daemon-side event filtering based on client verbosity preferences. By filtering events at daemon before transport, we reduce network bandwidth, serialization overhead, and client processing by 60-70%. The design maintains backward compatibility through optional protocol fields and preserves client autonomy through client-side `DisplayPolicy` as secondary filter.

## Problem & Solution

### Problem: Client-Side Filtering Overhead

RFC-0013 delivers all subscribed events regardless of client verbosity. RFC-0015 has 70+ event types, but clients at 'normal' verbosity filter out ~70% of events client-side, wasting network bandwidth, CPU (JSON serialization/deserialization), memory (event queues), and client processing.

**Root Cause**: Daemon has no knowledge of client verbosity preferences. `subscribe_thread` only specifies `thread_id`, no filtering preference mechanism.

### Solution: Daemon-Side Filtering

**Approach**: Extend `subscribe_thread` with optional `verbosity` field, filter at daemon sender_loop using RFC-0024's `VerbosityTier` classification.

**Event Flow**:
```
Backend → EventBus.publish(event, event_meta) → _filter_and_enqueue → [should_show check] → Client
```

**Benefits**: 60-70% event reduction, bandwidth/CPU/memory savings, maintained backward compatibility.

**Non-Goals**: Dynamic verbosity changes, per-thread verbosity, passthrough modes, replacing client filtering.

## Guiding Principles

1. **Filter Late, Per-Client** - Filter at sender_loop (latest stage), per-client preferences
2. **Reuse RFC-0024 VerbosityTier** - Use existing classification, integer comparison `tier <= verbosity`
3. **Backward Compatibility via Defaults** - Optional fields with defaults ('normal'), no breaking changes
4. **Client-Side Filtering Remains** - Daemon coarse-grained, client fine-grained (edge cases)

## Architecture

### Event Classification

| Domain | Default Tier | Visible at Verbosity |
|--------|--------------|----------------------|
| lifecycle, protocol, tool, subagent | DETAILED (2) | detailed, debug |
| output | QUIET (0) | all levels |
| error | QUIET (0) | always |

**Visibility**: `should_show(tier, verbosity)` = integer comparison `tier <= verbosity_value`.

**VerbosityLevel Values**: quiet=0, normal=1, detailed=2, debug=3.

### Protocol Extension

**Extended `subscribe_thread`**:
```json
{
  "type": "subscribe_thread",
  "thread_id": "string (required)",
  "verbosity": "string (optional: quiet|normal|detailed|debug, default: normal)"
}
```

**Extended `subscription_confirmed`**:
```json
{
  "type": "subscription_confirmed",
  "thread_id": "string",
  "client_id": "string",
  "verbosity": "string (echoes preference)"
}
```

### Data Model

**ClientSession Extension**:
```python
@dataclass
class ClientSession:
    verbosity: VerbosityLevel = "normal"  # NEW
```

### Filtering Flow

**Before**: Backend → EventBus → ClientSession.queue → Transport → Client → DisplayPolicy

**After**: Backend → EventBus(event, event_meta) → _filter_and_enqueue → [should_show check] → Transport → Client

**Implementation**: Extract `(event, event_meta)` tuple, check `should_show(event_meta.verbosity, session.verbosity)`, skip filtered events.

### Event Metadata Propagation

**EventBus.publish Enhancement**:
```python
async def publish(topic, event, event_meta=None):
    queue.put_nowait((event, event_meta))  # Tuple
```

**Backend Emission**:
```python
event_meta = REGISTRY.get_meta(event_type)
await event_bus.publish(topic, event_dict, event_meta=event_meta)
```

## Implementation Requirements

### 1. Protocol Handler

**File**: `src/soothe/daemon/_handlers.py`

**Handler**: Extract `verbosity` from message (default='normal'), validate, call `subscribe_thread(client_id, thread_id, verbosity)`, send confirmation with echoed verbosity.

### 2. ClientSessionManager

**File**: `src/soothe/daemon/client_session.py`

**subscribe_thread**: Accept `verbosity` parameter, set `session.verbosity`, subscribe to topic.

**ClientSession**: Add `verbosity: VerbosityLevel = "normal"` field.

### 3. EventBus

**File**: `src/soothe/daemon/event_bus.py`

**publish**: Accept optional `event_meta`, send `(event, event_meta)` tuple to queues.

### 4. Sender Loop

**File**: `src/soothe/daemon/client_session.py`

**_sender_loop**: Extract tuple, check `should_show(event_meta.verbosity, session.verbosity)`, skip filtered events, send only to matching clients.

### 5. Event Emission Sites

**Files**: `core/runner.py`, `cognition/*.py`, `backends/*/`, `subagents/*/`, `tools/*/`

**Pattern**: Lookup `event_meta = REGISTRY.get_meta(event_type)`, pass to `publish()`.

### 6. Client Updates

**Files**: `daemon/client.py`, `ux/tui/app.py`, `ux/cli/execution/daemon_runner.py`

**Pattern**: `subscribe_thread(thread_id, verbosity='normal')` (or user-specified).

## Performance Expectations

### Event Reduction

- **quiet**: ~90% (only QUIET tier: errors, assistant text, final reports)
- **normal**: ~60-70% (QUIET + NORMAL)
- **detailed**: ~30-40% (QUIET + NORMAL + DETAILED)
- **debug**: ~0% (all except INTERNAL)

**Note**: Debug still applies filtering (consistent behavior).

### Resource Savings

- **Network**: ~1KB saved per filtered event
- **CPU**: Reduced JSON encoding/decoding
- **Memory**: Reduced queue pressure (maxsize=100)
- **Client**: Reduced parsing, filtering

### Metrics

Track: `events_emitted`, `events_filtered`, `events_delivered`, `filtering_ratio`, `bandwidth_saved`.

## Backward Compatibility

### Protocol

**Old clients** (no verbosity): Daemon defaults to 'normal', identical to current behavior.

**New clients** (with verbosity): Daemon applies specified filtering.

### Event Format

**Queue tuples**: `(event_dict, event_meta)` new, `event_dict` legacy. Sender loop handles both.

### Client Filtering

**Hybrid approach**: Daemon coarse-grained (verbosity), client fine-grained (DisplayPolicy edge cases). Client autonomy preserved.

## Migration Strategy

### Phase 1: Daemon Implementation
- Extend ClientSession, subscribe_thread, EventBus.publish
- Implement sender_loop filtering
- Unit/integration tests, backward compatibility tests

### Phase 2: Event Emission
- Update all `EventBus.publish()` calls
- Add `REGISTRY.get_meta()` lookups
- Verify metadata for all event types

### Phase 3: Client Updates
- Update client.py, TUI, CLI headless
- Specify verbosity based on user preference
- Integration tests, performance benchmarks

### Phase 4: Metrics & Documentation
- Add filtering metrics
- Performance report
- Update documentation

## References

- RFC-0013: Daemon communication protocol
- RFC-0015: Progress event protocol
- RFC-0024: VerbosityTier unification
- RFC-0019: Unified event processing

---

*Daemon-side event filtering reduces network overhead by 60-70% while maintaining backward compatibility.*