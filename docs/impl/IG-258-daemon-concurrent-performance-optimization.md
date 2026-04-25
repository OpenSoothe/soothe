# IG-258: Soothe-Daemon Concurrent Performance Optimization

> **Status**: Planning
> **Priority**: High
> **Scope**: Core daemon architecture scalability improvements
> **Estimated Effort**: Large (multi-phase optimization)
> **Dependencies**: RFC-400 (Daemon Communication), RFC-0013 (Detach/Cancel)

---

## Context

The soothed is a sophisticated background agent runner built on pure asyncio with multi-transport architecture (WebSocket, HTTP REST, Unix socket). While the architecture is well-designed for async concurrency, performance bottleneck analysis has identified **10 critical bottlenecks** that limit scalability under high concurrent load (100+ clients, thousands of concurrent threads).

This IG addresses these bottlenecks to enable production-scale deployments while maintaining low latency and predictable resource usage.

---

## Motivation

**Current Pain Points:**
1. Input queue unbounded growth → memory pressure, latency spikes
2. WebSocket sequential broadcast → slow clients delay all others
3. Fire-and-forget task explosion → asyncio scheduler overhead
4. Event queue silent drops → critical events lost under high load
5. Sender loop sequential delivery → per-client throughput limited
6. Global LLM rate limiter → cross-thread contention, cascading delays
7. SQLite single connection → database I/O bottleneck
8. EventBus lock contention → hot path serialization
9. Shell initialization blocking → first command latency
10. Intent detection LLM call → subagent startup delay

**Goal:** Optimize daemon to handle 100+ concurrent clients with:
- Input latency < 100ms under normal load
- Event delivery latency < 50ms per client
- Zero event drops under 10k events/second
- Predictable memory usage (bounded queues)
- Fair resource distribution across threads

---

## Phased Approach

This optimization will be implemented in **three phases** based on severity and impact:

### Phase 1: Critical Bottlenecks (High Priority)
Fixes that prevent unbounded resource growth and event loss:
1. Input queue limit + backpressure
2. WebSocket parallel broadcast
3. Task pool for message dispatch
4. Event prioritization + overflow strategy
5. Sender loop batching

### Phase 2: Medium-Priority Bottlenecks
Fixes that reduce contention and blocking:
6. Thread-local LLM rate limiting
7. Async SQLite operations
8. EventBus lock optimization

### Phase 3: Low-Priority Optimizations
Latency improvements for specific operations:
9. Shell initialization optimization
10. Subagent intent detection optimization

---

## Phase 1 Implementation Plan

### **1. Input Queue Limit + Backpressure**

**Files to Modify:**
- `packages/soothe/src/soothe/daemon/server.py` - Add queue limit
- `packages/soothe/src/soothe/daemon/message_router.py` - Handle queue full
- `packages/soothe/src/soothe/daemon/query_engine.py` - DAEMON_BUSY response

**Implementation Steps:**

1. **Add configurable queue limit:**
```python
# server.py
self._current_input_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
    maxsize=self._config.daemon.max_input_queue_size  # New config option
)
```

2. **Add config option:**
```python
# daemon_config.py
max_input_queue_size: int = 1000  # Default: 1000 pending inputs
max_input_queue_size == 0  # Unlimited (legacy mode)
```

3. **Implement backpressure:**
```python
# message_router.py - dispatch()
try:
    await d._current_input_queue.put(msg_dict, timeout=0.1)
except asyncio.QueueFull:
    # Send DAEMON_BUSY error to client
    await self._send_error(client_id, "DAEMON_BUSY", "Input queue full, retry later")
    return
```

4. **Add queue depth monitoring:**
```python
# server.py - Add periodic queue depth logging
if d._current_input_queue.qsize() > 800:  # 80% threshold
    logger.warning("Input queue near capacity: %d/%d",
                   d._current_input_queue.qsize(), maxsize)
```

**Verification:**
- Load test with 100 clients sending inputs simultaneously
- Verify queue size stays bounded
- Verify DAEMON_BUSY responses sent when full
- Verify no memory growth under sustained load

---

### **2. WebSocket Parallel Broadcast**

**Files to Modify:**
- `packages/soothe/src/soothe/daemon/transports/websocket.py`

**Implementation Steps:**

1. **Parallelize broadcast sends:**
```python
# websocket.py - broadcast()
async def broadcast(self, message: dict[str, Any]) -> None:
    data = encode(message).rstrip(b"\n")

    # Parallel sends with timeout
    send_tasks = [
        asyncio.create_task(self._send_with_timeout(client, data, timeout=1.0))
        for client in self._clients
    ]

    results = await asyncio.gather(*send_tasks, return_exceptions=True)

    # Remove dead clients
    for client, result in zip(self._clients.keys(), results):
        if isinstance(result, Exception):
            self._clients.pop(client, None)
```

2. **Add send with timeout helper:**
```python
async def _send_with_timeout(self, client, data, timeout):
    try:
        await asyncio.wait_for(client.send(data.decode("utf-8")), timeout=timeout)
    except asyncio.TimeoutError:
        raise Exception(f"Send timeout for client {client}")
```

**Verification:**
- Measure broadcast latency with 100 clients
- Verify latency stays < 100ms even with slow clients
- Verify timeout kills dead clients quickly
- Test with artificial network delays

---

### **3. Task Pool for Message Dispatch**

**Files to Modify:**
- `packages/soothe/src/soothe/daemon/server.py`
- `packages/soothe/src/soothe/config/daemon_config.py`

**Implementation Steps:**

1. **Add dispatch semaphore:**
```python
# server.py
self._dispatch_semaphore = asyncio.Semaphore(
    self._config.daemon.max_concurrent_dispatches
)
self._dispatch_tasks: dict[str, asyncio.Task] = {}  # client_id -> Task
```

2. **Add config option:**
```python
# daemon_config.py
max_concurrent_dispatches: int = 50  # Limit concurrent message handlers
```

3. **Track dispatch tasks per client:**
```python
# server.py - _handle_transport_message()
async def _handle_transport_message(self, client_id: str, msg: dict[str, Any]):
    async with self._dispatch_semaphore:
        task = asyncio.create_task(
            self._message_router.dispatch(client_id, msg)
        )
        self._dispatch_tasks[client_id] = task
        try:
            await task
        finally:
            self._dispatch_tasks.pop(client_id, None)
```

4. **Cleanup on client disconnect:**
```python
# client_session.py - remove_session()
# Cancel pending dispatch tasks
if client_id in d._dispatch_tasks:
    d._dispatch_tasks[client_id].cancel()
```

**Verification:**
- Verify semaphore limits concurrent dispatches
- Verify tasks cancelled on disconnect
- Verify no stray tasks after client removal
- Load test with burst messages

---

### **4. Event Prioritization + Overflow Strategy**

**Files to Modify:**
- `packages/soothe/src/soothe/daemon/client_session.py`
- `packages/soothe/src/soothe/daemon/event_bus.py`
- `packages/soothe/src/soothe/core/event_catalog.py`

**Implementation Steps:**

1. **Add event priority levels:**
```python
# event_catalog.py
class EventPriority(Enum):
    CRITICAL = 0   # Errors, cancellation - never drop
    HIGH = 1       # Tool results, subagent output
    NORMAL = 2     # Heartbeat, status updates
    LOW = 3        # Debug, trace events
```

2. **Priority-aware queue:**
```python
# client_session.py
event_queue: asyncio.PriorityQueue[tuple[int, dict]] = field(
    default_factory=lambda: asyncio.PriorityQueue(maxsize=10000)
)
```

3. **Overflow strategy:**
```python
# event_bus.py - publish()
# Check queue depth
if queue.qsize() > 8000:  # 80% threshold
    # Drop LOW priority events
    if event_meta.priority == EventPriority.LOW:
        logger.debug("Dropping low-priority event due to queue pressure")
        continue

# Try to put with priority
try:
    queue.put_nowait((event_meta.priority, event))
except asyncio.QueueFull:
    if event_meta.priority == EventPriority.CRITICAL:
        # Never drop critical - block until space available
        await queue.put((event_meta.priority, event))
    else:
        logger.warning("Dropping event %s due to queue overflow", event_type)
```

4. **Client notification:**
```python
# event_bus.py - publish()
if queue.qsize() > 8000:
    # Send warning to client
    await self._send_queue_warning(client_id, queue.qsize(), maxsize)
```

**Verification:**
- Simulate event flood (10k events/sec)
- Verify critical events never dropped
- Verify low priority dropped first
- Verify client receives queue warnings
- Test event ordering (priority queue preserves order)

---

### **5. Sender Loop Batching**

**Files to Modify:**
- `packages/soothe/src/soothe/daemon/client_session.py`

**Implementation Steps:**

1. **Batching accumulator:**
```python
# client_session.py - _sender_loop()
batch = []
batch_timeout = 0.05  # 50ms batch window

async def _sender_loop(self, session):
    while True:
        try:
            # Wait for first event or batch timeout
            event_data = await asyncio.wait_for(
                session.event_queue.get(),
                timeout=batch_timeout
            )
            batch.append(event_data)
        except asyncio.TimeoutError:
            if not batch:
                continue  # No events, retry

        # Gather remaining events in batch window
        while not session.event_queue.empty() and len(batch) < 10:
            try:
                event_data = session.event_queue.get_nowait()
                batch.append(event_data)
            except asyncio.QueueEmpty:
                break

        # Send batch
        if batch:
            await self._send_batch(session, batch)
            batch.clear()
```

2. **Batch send helper:**
```python
async def _send_batch(self, session, events):
    # Group related events (e.g., tool call series)
    grouped = self._group_related_events(events)

    for group in grouped:
        await session.transport.send(session.transport_client, group)
```

**Verification:**
- Measure event delivery throughput per client
- Verify batching reduces send overhead
- Verify no event ordering violations
- Test with rapid tool call series

---

## Phase 2 Implementation Plan

### **6. Thread-Local LLM Rate Limiting**

**Files to Modify:**
- `packages/soothe/src/soothe/middleware/llm_rate_limit.py`

**Implementation:**
- Replace global sliding window with thread-local budgets
- Fair distribution: total RPM / active threads
- Non-blocking queue with scheduled execution
- Per-thread semaphore isolation

**Details:** TBD in follow-up planning

---

### **7. Async SQLite Operations**

**Files to Modify:**
- `packages/soothe/src/soothe/backends/persistence/sqlite_store.py`

**Implementation:**
- Replace threading.Lock with asyncio.Lock
- Wrap all methods with `asyncio.to_thread`
- Add connection pool (multiple readers)
- Consider migration to aiosqlite library

**Details:** TBD in follow-up planning

---

### **8. EventBus Lock Optimization**

**Files to Modify:**
- `packages/soothe/src/soothe/daemon/event_bus.py`

**Implementation:**
- Replace asyncio.Lock with reader-writer pattern
- Copy-on-write subscriber dict
- Multiple concurrent publishers
- Lock-free subscriber lookups

**Details:** TBD in follow-up planning

---

## Phase 3 Implementation Plan

### **9. Shell Initialization Optimization**

**Files to Modify:**
- `packages/soothe/src/soothe/toolkits/execution.py`

**Implementation:**
- Pre-initialize shells during thread startup
- Async pexpect wrapper via asyncio.to_thread
- Remove/reduce responsiveness testing
- Shell pool for immediate availability

**Details:** TBD in follow-up planning

---

### **10. Subagent Intent Detection Optimization**

**Files to Modify:**
- `packages/soothe/src/soothe/subagents/browser/implementation.py`

**Implementation:**
- Cache intent detection results for similar prompts
- Move intent detection to planning phase
- Pre-warm browser sessions
- Parallel step execution where possible

**Details:** TBD in follow-up planning

---

## Testing Strategy

### Load Testing Infrastructure
1. Create synthetic client simulator (WebSocket client)
2. Generate load patterns:
   - Burst inputs (100 clients, 10 inputs/sec each)
   - Sustained moderate load (50 clients, continuous)
   - Event flood (10k events/second)
3. Measure metrics:
   - Queue depths
   - Task counts
   - Latency distributions
   - Memory usage
   - Event drop rates

### Performance Benchmarks
- Input latency baseline vs optimized
- Broadcast latency 10 vs 100 clients
- Event throughput per client
- LLM call latency under contention
- Memory growth under sustained load

### Integration Tests
- Verify no regressions in existing tests
- Add new tests for queue limits, backpressure
- Add tests for event prioritization
- Add tests for task cleanup

---

## Risk Assessment

**High-Risk Changes:**
- Input queue limit: Could reject valid inputs under load
  - Mitigation: Configurable limit, clear error messages
- Event prioritization: Could drop important events
  - Mitigation: Never drop CRITICAL, extensive testing
- Task pool: Could deadlock if semaphore not released
  - Mitigation: Timeout on dispatch, proper cleanup

**Medium-Risk Changes:**
- WebSocket parallel broadcast: Could amplify network congestion
  - Mitigation: Timeout per send, fair scheduling
- Sender batching: Could delay urgent events
  - Mitigation: Priority batching, timeout limits

---

## Monitoring Requirements

Add metrics for production monitoring:
1. Queue depth metrics (input, event queues)
2. Task count metrics (active dispatches)
3. Event drop rate metrics
4. Broadcast latency metrics
5. LLM call wait time metrics

Integration with existing daemon health checks.

---

## Documentation Updates

1. Update RFC-400 with queue limit specifications
2. Update daemon_config.py with new config options
3. Update docs/user_guide.md with backpressure behavior
4. Add troubleshooting guide for queue overflow

---

## Success Criteria

**Quantitative Goals:**
- Input latency < 100ms under 100 clients
- Broadcast latency < 100ms under 100 clients
- Zero event drops under 10k events/sec
- Memory bounded (no growth under sustained load)
- No stray tasks after client disconnects

**Qualitative Goals:**
- Clear error messages for backpressure
- Predictable behavior under load
- Fair resource distribution
- No regressions in existing tests

---

## Implementation Timeline

**Phase 1 (Weeks 1-3):**
- Week 1: Input queue limit, WebSocket parallel broadcast
- Week 2: Task pool, event prioritization
- Week 3: Sender batching, integration testing

**Phase 2 (Weeks 4-6):**
- Week 4: Thread-local LLM rate limiting
- Week 5: Async SQLite operations
- Week 6: EventBus optimization, testing

**Phase 3 (Weeks 7-8):**
- Week 7: Shell initialization, intent detection
- Week 8: Final testing, documentation, benchmarking

---

## Dependencies

**RFCs:**
- RFC-400 (Daemon Communication Protocol)
- RFC-0013 (Detach/Cancel Behavior)
- RFC-0022 (Verbosity Filtering)

**Prior IGs:**
- IG-254 (Event System Optimization) - Event metadata
- IG-253 (Subagent Logging) - Event priorities

---

## Notes

- Each phase requires full testing before proceeding
- Performance benchmarks must be established before changes
- Monitor production metrics during rollout
- Consider A/B testing for high-risk changes
- Document all config changes in env.example

---

## References

- Performance bottleneck analysis (plan file)
- RFC-000 System Conceptual Design
- Asyncio best practices documentation
- Production load testing methodology