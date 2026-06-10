# IG-477: Memory Leak Fix and tracemalloc Improvements

## Summary

Fix the unbounded response queue memory leak in `thread_runner.py` and improve `tracemalloc` profiling to properly capture and verify the diagnosis.

## Problem Statement

### Memory Leak (Primary)
RSS grows from ~1 GB to ~24 GB during active queries due to:
1. Unbounded `threading.Queue` at `thread_runner.py:493`
2. Unbounded `asyncio.Queue` at `thread_runner.py:752`
3. `put_nowait()` in `response_bridge.py:51-57` without backpressure

### tracemalloc Not Capturing Leak (Secondary)
tracemalloc shows only ~0.9 MB traced while RSS grows by ~19 GiB because:
1. `statistics("lineno")` groups by count, not size - large single objects underrepresented
2. Missing large-object sampling (allocations > 100KB)
3. Need better traceback visualization for queue-related allocations

## Implementation Steps

### Step 1: Bound Response Queues in thread_runner.py

**File**: `packages/soothe-daemon/src/soothe_daemon/runner/thread_runner.py`

**Changes**:
1. Line 493: Add `maxsize=100` to worker threading.Queue
2. Line 752: Add `maxsize=100` to per-request asyncio.Queue
3. Add configuration option for queue size

```python
# Line 493 - worker response queue (threading.Queue)
response_queue: queue.Queue = queue.Queue(maxsize=100)

# Line 752 - per-request asyncio.Queue
response_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=100)
```

### Step 2: Add Backpressure in response_bridge.py

**File**: `packages/soothe-daemon/src/soothe_daemon/runner/response_bridge.py`

**Changes**:
Add `put()` with timeout instead of `put_nowait()` to slow worker when queue is full.

```python
def _deliver(self, msg_type: str, payload: Any) -> None:
    """Run on the main loop thread; map worker types to asyncio.Queue tuples."""
    try:
        if msg_type == WORKER_MSG_TIMEOUT:
            self._queue.put((WORKER_MSG_ERROR, payload), timeout=1.0)
        elif msg_type == WORKER_MSG_CANCELLED:
            self._queue.put((WORKER_MSG_ERROR, asyncio.CancelledError()), timeout=1.0)
        elif msg_type == WORKER_MSG_CHUNK:
            self._queue.put((WORKER_MSG_CHUNK, payload), timeout=1.0)
        elif msg_type == WORKER_MSG_DONE:
            self._queue.put_nowait((WORKER_MSG_DONE, None))  # Terminal, don't block
        elif msg_type == WORKER_MSG_ERROR:
            self._queue.put((WORKER_MSG_ERROR, payload), timeout=1.0)
        else:
            logger.warning("ResponsePusher: unknown worker msg_type=%s", msg_type)
    except asyncio.QueueFull:
        logger.warning(
            "ResponsePusher: queue full (maxsize=100), dropping %s msg_type=%s",
            "chunk" if msg_type == WORKER_MSG_CHUNK else "other",
            msg_type,
        )
```

### Step 3: Update MemoryProfiler to Capture Large Allocations

**File**: `packages/soothe-daemon/src/soothe_daemon/services/memory_profiler.py`

**Changes**:
1. Add `statistics("traceback")` ranked by size for large objects
2. Add large allocation sampling (filter for > 100KB)
3. Add queue-specific tracing helper

```python
def get_large_allocations(self, min_size_kb: float = 100.0) -> list[dict[str, Any]]:
    """Get allocations larger than threshold, ranked by size.

    This captures large single objects that statistics("lineno") misses.
    """
    if not self._running:
        return []

    snapshot = tracemalloc.take_snapshot()
    # Use traceback grouping to see full allocation chain
    stats = snapshot.statistics("traceback")

    large_allocs = []
    for stat in stats:
        size_kb = stat.size / 1024
        if size_kb >= min_size_kb:
            tb_lines = [f"{t.filename}:{t.lineno}" for t in stat.traceback]
            large_allocs.append({
                "size_kb": round(size_kb, 2),
                "count": stat.count,
                "traceback": tb_lines,
                "avg_size_kb": round(size_kb / stat.count, 2),
            })

    large_allocs.sort(key=lambda x: x["size_kb"], reverse=True)
    return large_allocs[:self._config.top_allocations_limit]
```

### Step 4: Add Queue Depth Metrics

**File**: `packages/soothe-daemon/src/soothe_daemon/services/memory_profiler.py`

Add method to report queue depths for debugging:

```python
def get_queue_metrics(self) -> dict[str, Any]:
    """Get queue depths from thread pool for debugging."""
    from soothe_daemon.runner.thread_runner import ThreadPool

    pool = ThreadPool._shared_pool
    if pool is None:
        return {"error": "ThreadPool not initialized"}

    metrics = {
        "pending_responses_count": len(pool._pending_responses),
        "workers": {},
    }

    for worker_id, worker in pool._workers.items():
        metrics["workers"][worker_id] = {
            "status": worker.status.value,
            "response_queue_size": worker.response_queue.qsize(),
            "current_loop_id": worker.current_loop_id,
        }

    return metrics
```

### Step 5: Add Configuration for Queue Bounds

**File**: `packages/soothe-daemon/src/soothe_daemon/config/models.py`

Add to `ThreadPoolConfig`:

```python
response_queue_maxsize: int = Field(
    default=100,
    ge=10,
    le=1000,
    description="Maximum items in response queues (bounds memory growth)",
)
```

## Testing

1. Run query test with memory profiling before fix → verify leak
2. Apply fixes
3. Run same query test → verify RSS stays bounded (< 2 GB for simple query)
4. Verify queue metrics endpoint shows bounded queues

## Files Changed

| File | Changes |
|------|---------|
| `thread_runner.py` | Bound queues (lines 493, 752), add queue size config |
| `response_bridge.py` | Add backpressure with `put(timeout=1.0)` |
| `memory_profiler.py` | Add `get_large_allocations()`, `get_queue_metrics()` |
| `config/models.py` | Add `response_queue_maxsize` to ThreadPoolConfig |
| `http_rest.py` | Add `/api/v1/memory/queues` endpoint |

## Status

- [x] Step 1: Bound response queues in thread_runner.py (lines 493, 752)
- [x] Step 2: Add backpressure in response_bridge.py (put with timeout)
- [x] Step 3: Add large allocation tracking in memory_profiler.py
- [x] Step 4: Add queue metrics endpoint in memory_profiler.py
- [x] Step 5: Add `/api/v1/memory?mode=queues` and `mode=large` endpoints
- [ ] Build Docker image v0.6.2 and verify fix

## Verification Needed

After building new image, run the same test to verify:
1. RSS stays bounded (< 2 GB for simple query)
2. `/api/v1/memory?mode=queues` shows queue depths near 0 when idle
3. `/api/v1/memory?mode=large` captures any remaining large allocations