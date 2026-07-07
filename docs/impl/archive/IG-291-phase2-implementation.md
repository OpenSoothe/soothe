# IG-258 Phase 2: Medium-Priority Concurrent Optimizations

> **Status**: Implementation Started
> **Phase**: 2 (Medium-Priority Optimizations)
> **Dependencies**: Phase 1 (Complete ✅)
> **Estimated Effort**: 3 weeks

---

## Phase 2 Overview

Phase 1 addressed critical bottlenecks preventing unbounded resource growth. Phase 2 focuses on **reducing contention and blocking** to improve throughput and reduce cascading delays across threads.

**Optimizations**:
1. **Thread-local LLM rate limiting** (Bottleneck #6) - Prevent cross-thread RPM contention
2. **Async SQLite operations** (Bottleneck #7) - Eliminate sync blocking in persistence
3. **EventBus lock optimization** (Bottleneck #8) - Reduce hot path contention

---

## Optimization 1: Thread-Local LLM Rate Limiting

### Problem Analysis

**Current Bottleneck** (from IG-258 plan):
- Global sliding window - all threads share RPM budget
- Blocking `asyncio.sleep()` stalls LLM calls across ALL threads
- Semaphore limit (default: 10 concurrent requests) shared globally
- One slow LLM call can monopolize semaphore (timeout: 60s)

**Impact**:
- All threads compete for shared RPM budget
- One thread hitting limit delays ALL others
- Cascading delays across entire daemon
- Semaphore starvation from slow calls

**Location**: `packages/soothe/src/soothe/middleware/llm_rate_limit.py:138-169`

### Solution Architecture

**Thread-Local RPM Budgets**:
- Replace global sliding window with per-thread budget
- Fair distribution: total RPM / active threads
- Each thread has independent semaphore (prevent cross-thread starvation)
- Non-blocking queue with scheduled execution

**Implementation Strategy**:

```python
# Current (global contention)
class LLMRateLimiter:
    def __init__(self, rpm_limit, max_concurrent):
        self._request_times = []  # Global window
        self._semaphore = asyncio.Semaphore(max_concurrent)  # Shared
    
    async def acquire(self):
        # All threads compete for same budget
        if len(self._request_times) >= self._rpm_limit:
            await asyncio.sleep(wait_seconds)  # Blocks ALL threads!

# Proposed (thread-local isolation)
class LLMRateLimiterV2:
    def __init__(self, rpm_limit_global, max_concurrent_per_thread):
        self._rpm_limit_global = rpm_limit_global
        self._max_concurrent_per_thread = max_concurrent_per_thread
        self._thread_budgets: dict[str, ThreadBudget] = {}
        self._budget_lock = asyncio.Lock()  # Only for budget allocation
    
    async def acquire(self, thread_id: str):
        # Get or create thread-local budget
        budget = await self._get_thread_budget(thread_id)
        
        # Use thread-local semaphore (no cross-thread contention)
        async with budget.semaphore:
            # Thread-local RPM check
            await budget.wait_for_rpm_slot()
            return budget.record_request()
    
    async def _get_thread_budget(self, thread_id: str) -> ThreadBudget:
        async with self._budget_lock:
            if thread_id not in self._thread_budgets:
                # Fair distribution: global RPM / active threads
                active_threads = len(self._thread_budgets)
                thread_rpm = self._rpm_limit_global // max(active_threads + 1, 1)
                self._thread_budgets[thread_id] = ThreadBudget(
                    rpm_limit=thread_rpm,
                    semaphore_max=self._max_concurrent_per_thread,
                )
            return self._thread_budgets[thread_id]

@dataclass
class ThreadBudget:
    rpm_limit: int
    semaphore_max: int
    request_times: list[float] = field(default_factory=list)
    semaphore: asyncio.Semaphore = field(init=False)
    
    def __post_init__(self):
        self.semaphore = asyncio.Semaphore(self.semaphore_max)
    
    async def wait_for_rpm_slot(self):
        """Wait for RPM slot (thread-local, no cross-thread blocking)."""
        now = time.time()
        # Remove requests older than 60 seconds
        self.request_times = [t for t in self.request_times if now - t < 60.0]
        
        if len(self.request_times) >= self.rpm_limit:
            oldest = self.request_times[0]
            wait_seconds = oldest + 60.0 - now
            await asyncio.sleep(wait_seconds)  # Only blocks THIS thread
        
    def record_request(self) -> float:
        """Record request time and return timestamp."""
        now = time.time()
        self.request_times.append(now)
        return now
```

### Implementation Steps

1. **Create ThreadBudget dataclass** in `llm_rate_limit.py`
2. **Refactor LLMRateLimiter to thread-local architecture**:
   - Add `_thread_budgets` dict
   - Add `_get_thread_budget()` method
   - Modify `acquire()` to accept `thread_id`
   - Replace global semaphore with per-thread semaphore
3. **Update middleware integration**:
   - Pass `thread_id` to rate limiter (from context)
   - Handle thread budget cleanup on thread end
4. **Add configuration options**:
   - `llm_rate_limit_per_thread_rpm: bool = True`
   - `llm_max_concurrent_per_thread: int = 10`

### Verification

**Test scenarios**:
1. **Isolation test**: Two threads hitting RPM limit independently
   - Thread A at limit → only Thread A waits
   - Thread B continues unaffected
2. **Fair distribution test**: RPM budget split equally across active threads
   - Global 100 RPM, 10 threads → each gets 10 RPM
3. **Semaphore isolation**: Slow call in Thread A doesn't block Thread B
4. **Budget cleanup**: Thread end removes budget, redistributes to others

**Metrics**:
- LLM call latency per thread (no cascading delays)
- RPM budget fairness (equal distribution)
- Semaphore wait time per thread

---

## Optimization 2: Async SQLite Operations

### Problem Analysis

**Current Bottleneck**:
- Single SQLite connection shared across all threads
- Threading lock (sync) blocks async threads
- All methods are synchronous - blocking async execution
- 30-second timeout on lock acquisition

**Impact**:
- All persistence operations serialized through single connection
- Threading lock blocks event loop (sync lock in async context)
- High I/O load creates contention
- Timeout can cause operations to fail

**Location**: `packages/soothe/src/soothe/backends/persistence/sqlite_store.py:35,53,87-136`

### Solution Architecture

**Async Wrapper Pattern**:
- Replace `threading.Lock` with `asyncio.Lock`
- Wrap all sync SQLite operations with `asyncio.to_thread`
- Connection pool (multiple readers, one writer)
- Async-to-thread wrapper for sync operations

**Implementation Strategy**:

```python
# Current (sync blocking)
class SQLiteStore:
    def __init__(self, path):
        self._lock = threading.Lock()  # Sync lock!
        self._conn = sqlite3.connect(path)  # Single connection
    
    def save(self, key: str, value: str) -> None:  # Sync method
        with self._lock:  # Blocks async threads
            self._conn.execute(...)

# Proposed (async non-blocking)
class SQLiteStoreV2:
    def __init__(self, path, pool_size=5):
        self._lock = asyncio.Lock()  # Async lock
        self._path = path
        self._writer_conn: sqlite3.Connection | None = None
        self._reader_pool: list[sqlite3.Connection] = []
        self._pool_size = pool_size
        self._pool_semaphore = asyncio.Semaphore(pool_size)
    
    async def save(self, key: str, value: str) -> None:  # Async method
        async with self._lock:  # Async lock (doesn't block event loop)
            await asyncio.to_thread(self._sync_save, key, value)
    
    def _sync_save(self, key: str, value: str) -> None:
        """Sync implementation executed in thread pool."""
        if not self._writer_conn:
            self._writer_conn = sqlite3.connect(self._path)
        self._writer_conn.execute(...)
    
    async def load(self, key: str) -> str | None:  # Async method
        async with self._pool_semaphore:  # Get reader connection
            conn = await self._get_reader_conn()
            result = await asyncio.to_thread(self._sync_load, conn, key)
            return result
    
    async def _get_reader_conn(self) -> sqlite3.Connection:
        """Get connection from reader pool."""
        async with self._lock:
            if not self._reader_pool:
                # Initialize pool
                for i in range(self._pool_size):
                    conn = sqlite3.connect(self._path)
                    self._reader_pool.append(conn)
            return self._reader_pool.pop() if self._reader_pool else sqlite3.connect(self._path)
```

**Alternative: aiosqlite library**:
- Native async SQLite library
- No manual `asyncio.to_thread` wrapping
- Connection pool built-in
- Better async integration

```python
# Using aiosqlite (simpler)
import aiosqlite

class SQLiteStoreV2:
    async def save(self, key: str, value: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(...)
    
    async def load(self, key: str) -> str | None:
        async with aiosqlite.connect(self._path) as db:
            result = await db.execute(...)
            return await result.fetchone()
```

### Implementation Steps

1. **Replace threading.Lock with asyncio.Lock**
2. **Convert all methods to async**:
   - `save()`, `load()`, `delete()`, `list_keys()`
   - Use `asyncio.to_thread()` for sync SQLite operations
3. **Add connection pool**:
   - Reader pool (5 connections for concurrent reads)
   - Writer connection (single writer for consistency)
   - Pool semaphore to limit concurrent readers
4. **Consider aiosqlite migration**:
   - If simpler and more performant
   - Evaluate dependency overhead
5. **Add configuration options**:
   - `sqlite_pool_size: int = 5`
   - `sqlite_use_aiosqlite: bool = False`

### Verification

**Test scenarios**:
1. **Async non-blocking**: Multiple concurrent SQLite operations
   - All operations proceed without blocking event loop
2. **Pool efficiency**: 5 concurrent reads use pool connections
   - No connection contention
3. **Lock contention**: Measure asyncio.Lock wait time vs threading.Lock
4. **Regression**: All persistence tests pass

**Metrics**:
- SQLite operation latency (async vs sync)
- Lock acquisition time (async vs threading.Lock)
- Pool utilization (connections in use)

---

## Optimization 3: EventBus Lock Optimization

### Problem Analysis

**Current Bottleneck**:
- Every publish acquires `asyncio.Lock`
- High publish frequency (every event from all threads)
- Lock held only for copying subscriber set, but still blocks
- No reader-writer pattern for concurrent reads

**Impact**:
- Lock contention in hot publish path
- Serializes subscriber lookups across all threads
- Can delay event delivery under high event volume

**Location**: `packages/soothe/src/soothe/daemon/event_bus.py:37-42`

### Solution Architecture

**Reader-Writer Pattern**:
- Multiple concurrent publishers (readers)
- Exclusive lock only for subscribe/unsubscribe (writers)
- Copy-on-write subscriber dict (avoid lock in hot path)

**Implementation Strategy**:

```python
# Current (lock on every publish)
class EventBus:
    def __init__(self):
        self._subscribers: dict[str, set[Queue]] = {}
        self._lock = asyncio.Lock()
    
    async def publish(self, topic, event, event_meta):
        async with self._lock:  # Every publish!
            queues = self._subscribers.get(topic, set()).copy()

# Proposed (lock-free publish)
class EventBusV2:
    def __init__(self):
        # Use regular dict (no lock for reads)
        self._subscribers: dict[str, set[Queue]] = {}
        self._write_lock = asyncio.Lock()  # Only for subscribe/unsubscribe
    
    async def publish(self, topic, event, event_meta):
        # NO LOCK! Direct read (atomic dict access)
        queues = self._subscribers.get(topic, set()).copy()
        
        # If no queues, early return (no lock needed)
        if not queues:
            return
        
        # Send to queues (no lock)
        dropped = 0
        for queue in queues:
            # Priority-aware overflow (from Phase 1)
            ...
    
    async def subscribe(self, topic, queue):
        async with self._write_lock:  # Write lock
            if topic not in self._subscribers:
                self._subscribers[topic] = set()
            self._subscribers[topic].add(queue)
    
    async def unsubscribe(self, topic, queue):
        async with self._write_lock:  # Write lock
            if topic in self._subscribers:
                self._subscribers[topic].discard(queue)
                if not self._subscribers[topic]:
                    del self._subscribers[topic]
```

**Alternative: aiolock reader-writer**:
- Third-party library with RWLock implementation
- More complex but proper reader-writer semantics

```python
# Using aiolock (if available)
from aiolock import RWLock

class EventBusV2:
    def __init__(self):
        self._subscribers: dict[str, set[Queue]] = {}
        self._rwlock = RWLock()
    
    async def publish(self, topic, event, event_meta):
        async with self._rwlock.reader:  # Multiple readers
            queues = self._subscribers.get(topic, set()).copy()
    
    async def subscribe(self, topic, queue):
        async with self._rwlock.writer:  # Exclusive writer
            ...
```

### Implementation Steps

1. **Rename lock to `_write_lock`** (clarify purpose)
2. **Remove lock from `publish()` method**:
   - Direct dict read (atomic in Python)
   - Early return if no subscribers
3. **Keep lock for `subscribe()` and `unsubscribe()`**:
   - Write operations need exclusive lock
   - Prevent concurrent modification
4. **Consider copy-on-write**:
   - Subscribe creates new dict entry (atomic)
   - Unsubscribe removes entry (atomic)
5. **Test concurrent publishing**:
   - Multiple threads publishing simultaneously
   - No lock contention

### Verification

**Test scenarios**:
1. **Concurrent publish**: 10 threads publishing to same topic
   - All proceed without blocking
2. **Subscribe during publish**: Subscribe while publishing
   - No race conditions
3. **Unsubscribe during publish**: Unsubscribe while publishing
   - Safe removal
4. **Performance**: Measure publish latency (lock vs lock-free)

**Metrics**:
- Publish latency (lock-free vs locked)
- Lock acquisition count (subscribe/unsubscribe only)
- Concurrent publish throughput

---

## Phase 2 Timeline

**Week 1**:
- Day 1-2: Thread-local LLM rate limiting implementation
- Day 3-4: Async SQLite operations implementation
- Day 5: EventBus lock optimization

**Week 2**:
- Day 1-3: Integration testing for all 3 optimizations
- Day 4-5: Performance benchmarks and regression testing

**Week 3**:
- Day 1-2: Documentation and validation
- Day 3-5: Production deployment preparation

---

## Testing Strategy

### Unit Tests

For each optimization:
- Isolation tests (no cross-thread/cross-operation contention)
- Performance tests (latency, throughput)
- Edge case tests (budget exhaustion, pool exhaustion)

### Integration Tests

- All 3 optimizations working together
- Concurrent daemon operation (100+ clients)
- LLM calls + SQLite ops + Event publishing simultaneously

### Regression Tests

- Full verification suite (`./scripts/verify_finally.sh`)
- All 1285+ unit tests pass
- No breaking changes

---

## Success Criteria

**Quantitative Goals**:
- LLM call latency: No cross-thread blocking (< 10ms wait)
- SQLite operation latency: < 50ms (async non-blocking)
- Event publish latency: < 5ms (lock-free hot path)
- Lock contention: < 1% (only subscribe/unsubscribe)

**Qualitative Goals**:
- Thread isolation verified
- No sync blocking in async code
- Event loop not blocked by persistence
- Clear separation of reader/writer locks

---

## Risk Assessment

**Medium-Risk Changes**:
- Thread-local budgets: Budget redistribution on thread end
  - Mitigation: Graceful redistribution, minimum budget floor
- Async SQLite: Connection pool exhaustion
  - Mitigation: Semaphore limit, fallback connection creation
- EventBus lock-free: Race conditions in subscriber dict
  - Mitigation: Python dict atomic operations, write lock for modification

---

## Monitoring Requirements

Add metrics for Phase 2:
1. Thread budget distribution (RPM per thread)
2. SQLite connection pool utilization
3. EventBus publish latency (lock-free)
4. Lock acquisition counts (write operations only)

---

## Documentation Updates

1. Update RFC-400 with thread-local rate limiting spec
2. Update daemon_config.py with Phase 2 config options
3. Update docs/user_guide.md with thread isolation behavior
4. Add troubleshooting guide for budget exhaustion

---

## Dependencies

**Phase 1**: Complete ✅ (all 6 optimizations validated)

**RFCs**:
- RFC-400 (Daemon Communication)
- RFC-0013 (Detach/Cancel)
- RFC-0022 (Verbosity Filtering)

**Libraries**:
- aiosqlite (optional, for async SQLite)
- aiolock (optional, for reader-writer lock)

---

## Notes

- Phase 2 builds on Phase 1 foundation
- All changes maintain backwards compatibility
- Performance improvements measurable with benchmarks
- Consider A/B testing for thread-local rate limiting

---

## References

- IG-258 Phase 1 validation results
- RFC-000 System Conceptual Design
- Asyncio best practices (async locks, to_thread)
- SQLite WAL mode concurrency documentation