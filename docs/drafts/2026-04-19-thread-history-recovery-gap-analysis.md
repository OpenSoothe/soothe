# Thread History Recovery Gap Analysis

**Date**: 2026-04-19
**Author**: Claude Code Analysis
**Status**: Gap Analysis - Implementation Planning Required

## Executive Summary

The current thread management implementation has significant gaps between design intent and actual behavior. Users expect full visual history recovery when selecting threads from `/threads` or using `thread continue`, but the implementation only recovers conversation messages, losing all activity cards, tool call visualizations, progress indicators, and custom UI events.

## Problem Statement

### User Expectations

When a user selects a thread from the TUI `/threads` command or runs `soothe thread continue`:

1. **Full History Recovery**: All displayed activities, cards, tool call visualizations, and conversation messages should be visible
2. **Running Thread Display**: If the recovered thread is actively running, current activity should also be displayed
3. **Complete Visual Reconstruction**: The recovered thread should look the same as when the user last saw it

### Current Reality

- Only conversation messages (user queries and assistant responses) are recovered
- All visual elements (tool call cards, progress events, custom activities) are lost
- No mechanism to detect or reconnect to running threads
- Thread recovery shows a "bare conversation" without the rich UI context

## Architecture Analysis

### Current Storage Systems

Thread history is split across two independent storage systems:

#### 1. LangGraph Checkpointer (Primary Storage)

**Location**: SQLite database at `~/.soothe/sessions.db`

**Purpose**: Agent state persistence for continuation

**Contents**:
- Conversation messages (user/assistant turns)
- Agent internal state variables
- Context metadata (tokens, summaries)
- Thread configuration

**Access Pattern**:
```python
# app.py line 3440: _fetch_thread_history_data()
state_values = await self._get_thread_state_values(thread_id)
messages = state_values.get("messages", [])
# Converts checkpoint messages → MessageData widgets
```

**Scope**: Only LangGraph's `messages` channel from checkpoint

#### 2. ThreadLogger (Secondary Storage)

**Location**: JSONL files at `~/.soothe/runs/{thread_id}/conversation.jsonl`

**Purpose**: Structured event logging for offline replay and audit

**Contents**:
```jsonl
{"timestamp": "...", "kind": "conversation", "role": "user", "text": "..."}
{"timestamp": "...", "kind": "conversation", "role": "assistant", "text": "..."}
{"timestamp": "...", "kind": "event", "namespace": [...], "classification": "tier2", "data": {...}}
{"timestamp": "...", "kind": "tool_call", "namespace": [...], "tool_name": "ls", "args_preview": "..."}
{"timestamp": "...", "kind": "tool_result", "namespace": [...], "tool_name": "ls", "content": "..."}
```

**Access Pattern**:
```python
# thread_logger.py line 188: read_recent_records()
records = [json.loads(line) for line in fh.readlines()[-limit:]]
# Returns all record kinds including events
```

**Scope**: Complete stream history including all visual events

### The Disconnect

**Thread recovery only reads from the checkpointer, completely ignoring ThreadLogger**.

This causes:
- Conversation messages → recovered ✓
- Tool call events → lost ✗
- Progress indicators → lost ✗
- Custom UI events → lost ✗
- Activity cards → lost ✗

## Detailed Gap Analysis

### Gap 1: Incomplete Thread History Recovery

#### Design Expectation

When selecting a thread from `/threads` or using `thread continue`, the full thread history including all displayed activities and cards should be recovered.

#### Current Implementation

**ThreadLogger** (`packages/soothe/src/soothe/logging/thread_logger.py` lines 84-186):
- Captures structured event records for offline replay
- Stores tool calls, tool results, custom events with tier classifications
- Provides `read_recent_records()` to access all history

**Thread Recovery** (`packages/soothe-cli/src/soothe_cli/tui/app.py` line 3440):
```python
async def _fetch_thread_history_data(self, thread_id: str) -> _ThreadHistoryPayload:
    state_values = await self._get_thread_state_values(thread_id)
    messages = state_values.get("messages", [])
    # Only checkpoint messages → no ThreadLogger events
    data = await asyncio.to_thread(self._convert_messages_to_data, messages)
    return _ThreadHistoryPayload(data, context_tokens)
```

**Missing**:
- No call to ThreadLogger to read event records
- No conversion from ThreadLogger events → MessageData widgets
- Complete visual history reconstruction

#### Impact

Users see "empty" threads with only text conversation, losing:
- Tool execution context (which files were edited, what commands ran)
- Progress feedback (subagent spawning, research steps)
- Visual richness (collapsible cards, status indicators)
- Execution timeline (when each action occurred)

### Gap 2: Thread Messages API Limited Scope

#### Current Implementation

**Daemon API** (`packages/soothe/src/soothe/core/thread/manager.py` line 418):
```python
async def get_thread_messages(self, thread_id: str, limit: int = 100) -> list[ThreadMessage]:
    logger_instance = ThreadLogger(thread_id=thread_id)
    records = logger_instance.read_recent_records(limit=limit + offset)

    # Convert to ThreadMessage format - BUT filters out events!
    return [
        ThreadMessage(
            timestamp=record.get("timestamp"),
            kind="conversation",
            role=record.get("role"),
            content=record.get("text", ""),
            metadata=record,
        )
        for record in records[offset : offset + limit]
        if record.get("kind") == "conversation"  # ← DELIBERATE FILTER
    ]
```

**Wire Protocol** (`packages/soothe/src/soothe/daemon/message_router.py` line 461):
```python
async def _handle_thread_messages(self, client_id: str, msg: dict[str, Any]):
    messages = await d._runner.get_persisted_thread_messages(thread_id)
    await d._send_client_message({
        "type": "thread_messages_response",
        "messages": [m.model_dump(mode="json") for m in messages],
        # Only conversation records, no events
    })
```

#### Design Gap

The API **deliberately filters** out event/activity records, preventing:
- TUI from reconstructing complete visual history
- CLI `thread export` from including execution context
- Third-party tools from accessing full thread replay data

#### Alternative Consideration

**Why this filtering exists**: The API was designed for lightweight conversation review, not full replay. Events were considered "internal" and too verbose for terminal review.

**But this conflicts with**: TUI's rich visual display where events are rendered as interactive cards, progress indicators, and contextual feedback.

### Gap 3: No Running Thread Activity Display

#### Design Expectation

When running `soothe thread continue` to recover the latest thread, if that thread is actively running in the daemon, the current activity should also be displayed.

#### Current Implementation

**TUI Connection** (`packages/soothe-cli/src/soothe_cli/tui/daemon_session.py`):
```python
async def connect(self, *, resume_thread_id: str | None = None):
    await connect_websocket_with_retries(self._client)
    status_event = await self._bootstrap_thread(resume_thread_id=resume_thread_id)
    # Creates/resumes thread but doesn't check if running
```

**Thread Recovery** (`packages/soothe-cli/src/soothe_cli/tui/app.py` line 4585):
```python
async def _resume_thread(self, thread_id: str):
    # 1. Fetch static history from checkpoints
    prefetched_payload = await self._fetch_thread_history_data(thread_id)

    # 2. Switch daemon session
    await self._daemon_session.switch_thread(thread_id)

    # 3. Load static history widgets
    await self._load_thread_history(thread_id=thread_id, preloaded_payload=prefetched_payload)

    # Missing: Check if thread is running, reconnect to stream
```

**Missing Components**:
1. No query for thread runtime status (`state: "running"` vs `"idle"`)
2. No mechanism to reconnect to active streaming session
3. No display of in-progress activities after recovery

#### Impact

**Scenario**: User starts a long-running research task, closes TUI, then runs `soothe thread continue` to check progress.

**Expected**: See the running task's progress, intermediate results, current step.

**Actual**: See static conversation history, no indication that task is running, no live updates.

### Gap 4: ThreadLogger Schema Mismatch

#### Current Storage Schema

**ThreadLogger stores** (`thread_logger.py` lines 100-106):
```python
{
    "timestamp": datetime.now(UTC).isoformat(),
    "kind": "event",
    "namespace": list(namespace),
    "classification": classify_event_to_tier(data.get("type"), namespace),
    "data": data,  # Raw event dict
}
```

**TUI MessageData needs** (`app.py` lines 362-368):
```python
class _ThreadHistoryPayload:
    messages: list[MessageData]  # Structured UI data

# MessageData requires:
{
    "message_type": MessageType.TOOL_CALL,  # Enum, not string
    "tool_name": str,                       # Extracted from event
    "tool_args": dict,                      # Structured args
    "status": ToolStatus,                   # Enum: pending/running/complete/error
    "result": str,                          # Formatted result
    "timestamp": datetime,                  # Proper datetime object
    "namespace": tuple,                     # Not list
    # Plus UI-specific: styling, collapsible state, display hints
}
```

#### Conversion Gap

ThreadLogger events are:
- Raw wire protocol dicts
- Missing UI-specific metadata
- Using different type representations (strings vs enums)
- Lacking status state transitions

**Required**: A conversion layer that:
1. Parses ThreadLogger event records
2. Maps event types → MessageType enums
3. Extracts tool metadata from event payloads
4. Reconstructs status progression from event sequence
5. Adds UI display hints (collapse state, styling)

### Gap 5: History Loading Architecture Disconnect

#### Current Flow

```
_resume_thread(thread_id)
  ↓
_fetch_thread_history_data(thread_id)
  ↓
_get_thread_state_values(thread_id)  ← LangGraph checkpoint only
  ↓
messages = state_values["messages"]  ← No ThreadLogger
  ↓
_convert_messages_to_data(messages)  ← Converts to MessageData
  ↓
_load_thread_history(messages)       ← Mounts widgets
```

#### Missing Flow

Should have parallel path:

```
_resume_thread(thread_id)
  ↓
_fetch_thread_history_data(thread_id)          ← Checkpoint messages
_fetch_thread_activity_events(thread_id)       ← ThreadLogger events (MISSING)
  ↓
_merge_history_sources(messages, events)       ← Combine both (MISSING)
  ↓
_convert_combined_to_data(combined)            ← Unified conversion (MISSING)
  ↓
_load_thread_history(combined_data)            ← Mount all widgets
```

#### Required Components

1. **`_fetch_thread_activity_events()`**: Read ThreadLogger JSONL records
2. **`_merge_history_sources()`**: Interleave messages and events chronologically
3. **`_convert_events_to_data()`**: Map ThreadLogger events → MessageData widgets
4. **Event-to-Widget Mapper**: Custom logic for each event type

## Root Cause Analysis

### The Fundamental Issue

Thread history is architecturally split:

1. **Agent Persistence Layer** (LangGraph Checkpointer)
   - Purpose: Enable agent continuation
   - Scope: Internal state + conversation messages
   - Format: Optimized for agent runtime
   - Location: SQLite database

2. **UI Audit Layer** (ThreadLogger)
   - Purpose: Human review and replay
   - Scope: Complete visual history
   - Format: Human-readable JSONL
   - Location: Per-thread log files

**But recovery only reads layer 1, ignoring layer 2.**

### Why This Split Exists

**Historical Context**:
- LangGraph checkpointer was primary persistence mechanism
- ThreadLogger added later for audit/debugging
- TUI evolved from simple terminal chat to rich visual display
- Thread recovery designed before visual complexity emerged

**Design Assumption** (now invalid):
> "Thread history = conversation messages"
> ThreadLogger was for "debug logs", not "UI replay"

**Reality**:
> ThreadLogger contains essential UI components
> Visual history is as important as conversation text

## Impact Assessment

### User Experience Degradation

| Scenario | Expected | Actual | Impact |
|----------|----------|--------|--------|
| Research thread recovery | See all web searches, sources, analysis steps | Only conversation text | Can't review research process |
| Code editing thread recovery | See which files edited, diffs applied | Only "I edited X" messages | Can't trace edit history |
| Debugging thread recovery | See tool calls, error messages, stack traces | Only problem/solution text | Loses debugging context |
| Running task continuation | See current progress, intermediate results | Static history only | Can't monitor active work |

### Feature Incompleteness

- `/threads` command shows threads but recovery is incomplete
- `thread export` exports only conversation, not execution context
- `thread stats` can't count activities/events (only messages)
- Thread comparison impossible (need full history)

### Data Loss

- Rich execution context discarded
- Audit trail incomplete
- Replay capability limited
- ThreadLogger data effectively unused

## Solution Design Requirements

### Requirements Overview

1. **Full History Recovery**: Reconstruct complete visual history from both sources
2. **Event-to-Widget Mapping**: Convert ThreadLogger events → TUI MessageData widgets
3. **Chronological Merging**: Interleave messages and events by timestamp
4. **Running Thread Reconnect**: Query runtime status, reconnect to active streams
5. **API Enhancement**: Thread messages API should support full history mode

### Design Constraints

1. **Performance**: Large threads must load efficiently (windowed rendering)
2. **Storage Efficiency**: Don't duplicate data across checkpoint and ThreadLogger
3. **Backward Compatibility**: Existing threads must remain readable
4. **Event Schema Evolution**: Handle ThreadLogger schema changes over time

### Implementation Strategy Options

#### Option A: Dual-Source Recovery (Recommended)

**Approach**: Read from both checkpoint and ThreadLogger, merge in TUI

**Steps**:
1. `_fetch_thread_history_data()` reads checkpoint messages
2. `_fetch_thread_activity_events()` reads ThreadLogger JSONL
3. `_merge_history_sources()` interleaves by timestamp
4. `_convert_events_to_data()` maps events → MessageData
5. `_load_thread_history()` mounts combined widgets

**Pros**:
- Complete history reconstruction
- Uses existing ThreadLogger data
- Minimal storage changes
- Clear separation of concerns

**Cons**:
- More complex recovery logic
- Need event-to-widget mapping layer
- ThreadLogger must be complete/accurate

#### Option B: Unified Storage

**Approach**: Store everything in LangGraph checkpoint (enhance state schema)

**Steps**:
1. Extend checkpoint schema to include events
2. AgentLoop logs events to checkpoint during execution
3. Recovery reads single unified source
4. No need for ThreadLogger merging

**Pros**:
- Single source of truth
- Simpler recovery logic
- Atomic state updates

**Cons**:
- Checkpoint size explosion
- LangGraph schema pollution
- Breaks checkpoint semantics (internal state vs UI history)
- Major refactoring required

#### Option C: ThreadLogger-Only

**Approach**: Store everything in ThreadLogger, checkpoint only for agent state

**Steps**:
1. ThreadLogger becomes primary history source
2. Checkpoint still for agent continuation
3. Recovery reads ThreadLogger exclusively
4. Include conversation in ThreadLogger (already done)

**Pros**:
- ThreadLogger already designed for audit/replay
- Clear separation: agent state vs UI history
- Simpler recovery (single source)

**Cons**:
- Need to ensure ThreadLogger completeness
- Checkpoint messages must sync with ThreadLogger
- ThreadLogger must be durable/reliable

### Recommended Approach

**Option A (Dual-Source Recovery)** is recommended:

1. **Minimal disruption**: Uses existing infrastructure
2. **Separation preserved**: Checkpoint for agent, ThreadLogger for UI
3. **Backward compatible**: Old threads still work (ThreadLogger may be sparse)
4. **Incremental rollout**: Can implement feature-by-feature

## Implementation Roadmap

### Phase 1: Event Reading Infrastructure

**Files**:
- `packages/soothe-cli/src/soothe_cli/tui/app.py`

**Changes**:
```python
async def _fetch_thread_activity_events(self, thread_id: str) -> list[dict]:
    """Read ThreadLogger JSONL events for thread."""
    logger_instance = ThreadLogger(thread_id=thread_id)
    records = await asyncio.to_thread(
        logger_instance.read_recent_records, limit=1000
    )
    return [r for r in records if r.get("kind") in ("event", "tool_call", "tool_result")]

async def _merge_history_sources(
    self,
    messages: list[Any],
    events: list[dict]
) -> list[tuple[str, Any]]:
    """Interleave messages and events chronologically."""
    # Convert to unified timeline with timestamps
    # Return list of (source_type, data) tuples
```

### Phase 2: Event-to-Widget Conversion

**Files**:
- `packages/soothe-cli/src/soothe_cli/tui/app.py`
- `packages/soothe-cli/src/soothe_cli/tui/widgets/message_store.py`

**Changes**:
```python
def _convert_event_to_message_data(self, event: dict) -> MessageData:
    """Convert ThreadLogger event to MessageData widget data."""
    kind = event.get("kind")

    if kind == "tool_call":
        return MessageData(
            message_type=MessageType.TOOL_CALL,
            tool_name=event.get("tool_name"),
            tool_args=json.loads(event.get("args_preview", "{}")),
            status=ToolStatus.COMPLETE,  # Historical events are complete
            timestamp=event.get("timestamp"),
            namespace=tuple(event.get("namespace", [])),
        )

    elif kind == "tool_result":
        return MessageData(
            message_type=MessageType.TOOL_RESULT,
            tool_name=event.get("tool_name"),
            result=event.get("content"),
            status=ToolStatus.COMPLETE,
            timestamp=event.get("timestamp"),
        )

    elif kind == "event":
        # Map custom events to appropriate MessageType
        classification = event.get("classification")
        data = event.get("data", {})
        event_type = data.get("type", "")

        # Use existing TUI event classification logic
        # (app.py has event → widget mapping)
```

### Phase 3: Recovery Flow Integration

**Files**:
- `packages/soothe-cli/src/soothe_cli/tui/app.py`

**Changes**:
```python
async def _fetch_thread_history_data(self, thread_id: str) -> _ThreadHistoryPayload:
    # 1. Read checkpoint messages (existing)
    state_values = await self._get_thread_state_values(thread_id)
    messages = state_values.get("messages", [])

    # 2. Read ThreadLogger events (NEW)
    events = await self._fetch_thread_activity_events(thread_id)

    # 3. Merge sources (NEW)
    combined = await self._merge_history_sources(messages, events)

    # 4. Convert to MessageData (NEW - handle both message and event types)
    data = await asyncio.to_thread(self._convert_combined_to_data, combined)

    return _ThreadHistoryPayload(data, context_tokens)
```

### Phase 4: Running Thread Detection

**Files**:
- `packages/soothe/src/soothe/daemon/message_router.py`
- `packages/soothe-cli/src/soothe_cli/tui/daemon_session.py`
- `packages/soothe-cli/src/soothe_cli/tui/app.py`

**Changes**:
```python
# daemon: Add thread status query
async def _handle_thread_status(self, client_id: str, msg: dict[str, Any]):
    thread_id = msg["thread_id"]
    thread_state = self._thread_registry.get(thread_id)

    status = {
        "thread_id": thread_id,
        "state": "idle" if not thread_state else (
            "running" if thread_state.query_running else "idle"
        ),
        "has_active_query": thread_state.query_running if thread_state else False,
    }

    await d._send_client_message(client_id, {"type": "thread_status_response", **status})

# TUI: Query status on recovery
async def _resume_thread(self, thread_id: str):
    # ...existing history loading...

    # NEW: Check if running
    status = await self._daemon_session.query_thread_status(thread_id)
    if status.get("state") == "running":
        # Reconnect to active stream
        # Display current activity
        await self._reconnect_running_thread(thread_id)
```

### Phase 5: API Enhancement

**Files**:
- `packages/soothe/src/soothe/core/thread/manager.py`
- `packages/soothe/src/soothe/daemon/message_router.py`

**Changes**:
```python
async def get_thread_messages(
    self,
    thread_id: str,
    limit: int = 100,
    include_events: bool = False,  # NEW parameter
) -> list[ThreadMessage]:
    logger_instance = ThreadLogger(thread_id=thread_id)
    records = logger_instance.read_recent_records(limit=limit)

    # NEW: Support full history mode
    if include_events:
        return [
            ThreadMessage(
                timestamp=record.get("timestamp"),
                kind=record.get("kind"),  # Preserve actual kind
                role=record.get("role"),
                content=record.get("text") or record.get("content"),
                metadata=record,
            )
            for record in records
        ]
    else:
        # Legacy: conversation only
        return [
            ThreadMessage(...)
            for record in records
            if record.get("kind") == "conversation"
        ]
```

## Testing Requirements

### Unit Tests

1. **Event Reading**: Test `_fetch_thread_activity_events()` with mock ThreadLogger
2. **Event Conversion**: Test `_convert_event_to_message_data()` for each event type
3. **Chronological Merging**: Test interleaving messages and events by timestamp
4. **Running Status**: Test thread status query and reconnect logic

### Integration Tests

1. **Full Recovery**: Create thread with activities, recover in new TUI session
2. **Large Thread**: Test performance with 1000+ events
3. **Running Thread**: Test reconnecting to active daemon query
4. **Schema Evolution**: Test reading old ThreadLogger formats

### User Acceptance Tests

1. **Research Thread**: Create research thread, recover, verify all sources visible
2. **Edit History**: Edit multiple files, recover, verify edit cards present
3. **Running Task**: Start long task, close TUI, recover, see current progress
4. **Thread Export**: Export with events, verify complete history in export

## Migration Considerations

### Backward Compatibility

**Old Threads** (ThreadLogger sparse or missing):
- Recovery should gracefully handle missing ThreadLogger files
- Fall back to checkpoint-only recovery (current behavior)
- No errors, just reduced visual richness

**New Threads** (ThreadLogger complete):
- Full history recovery enabled
- All visual elements present

### Data Migration

No migration required:
- ThreadLogger already capturing events
- Checkpoint unchanged
- Only recovery logic changes

### Schema Evolution

**ThreadLogger Event Types** may change over time:
- Need version detection in event conversion
- Unknown event types → fallback handling
- Maintain compatibility layer

## Open Questions

### Q1: ThreadLogger Completeness Guarantee

**Question**: How do we ensure ThreadLogger captures all events?

**Current Risk**: Some events may bypass ThreadLogger logging

**Solution Options**:
- Audit all event emission paths
- Add logging middleware at event bus level
- Verification tests comparing checkpoint vs ThreadLogger

### Q2: Event Deduplication

**Question**: Do checkpoint messages and ThreadLogger events overlap?

**Analysis**:
- Checkpoint `messages` channel includes tool call/result messages
- ThreadLogger also logs `tool_call` and `tool_result` events
- **Risk**: Duplicate tool displays in recovery

**Solution**: Deduplication logic in `_merge_history_sources()`
- Match tool call events with AIMessage.tool_calls
- Match tool result events with ToolMessage.content

### Q3: ThreadLogger Storage Longevity

**Question**: ThreadLogger retention is 100 days, checkpoints persist indefinitely

**Impact**:
- Old threads (>100 days) lose visual history
- Only conversation remains

**Solution Options**:
- Increase ThreadLogger retention (configurable)
- Archive ThreadLogger to checkpoint on thread completion
- Accept limitation (visual history has time limit)

### Q4: Performance with Large Threads

**Question**: How does loading 1000+ events affect TUI startup?

**Current Mitigation**: Windowed rendering (only last N widgets mounted)

**Need**:
- Benchmark recovery time with large ThreadLogger
- Lazy loading for events beyond window
- Progress indicator during recovery

### Q5: Running Thread Stream Reconnect

**Question**: How to reconnect to daemon's active event stream?

**Current Architecture**: Daemon streams to specific WebSocket client

**Challenge**:
- New TUI client needs to "join" existing stream
- Daemon must support multiple clients per thread
- Event bus routing for late-joining clients

**Solution**: TBD (requires daemon protocol design)

## Conclusion

The thread history recovery gap is a significant user experience deficiency caused by architectural split between agent persistence (checkpoint) and UI audit (ThreadLogger). The recommended solution is **dual-source recovery** that merges both sources to reconstruct complete visual history.

Implementation should proceed in phases:
1. Event reading infrastructure
2. Event-to-widget conversion
3. Recovery flow integration
4. Running thread detection
5. API enhancement

This will transform thread recovery from "bare conversation" to "complete visual replay", matching user expectations and enabling full thread management capabilities.

## Next Steps

1. **Design Review**: Review this analysis with team
2. **Implementation Plan**: Create detailed implementation guide
3. **Prototype**: Build Phase 1 (event reading) to validate approach
4. **Performance Testing**: Benchmark with large threads
5. **Incremental Rollout**: Deploy feature-by-feature to minimize risk

---

**References**:
- ThreadLogger implementation: `packages/soothe/src/soothe/logging/thread_logger.py`
- Thread recovery: `packages/soothe-cli/src/soothe_cli/tui/app.py` lines 3440-3472, 4585-4675
- ThreadManager API: `packages/soothe/src/soothe/core/thread/manager.py` line 418
- Daemon protocol: `packages/soothe/src/soothe/daemon/message_router.py` lines 461-493
- TUI daemon session: `packages/soothe-cli/src/soothe_cli/tui/daemon_session.py`