# IG-411: Worker Pool Robustness Enhancement

**Status**: Completed
**Date**: 2026-05-10

---

## Context

Query `019e0dc0-7301-7e11-96f5-de2ab6827815` hung for 60 minutes due to:
1. Explore subagent synthesis took **10569s (~176 minutes)** - sentence_transformers embedding model loading failed
2. No cooperative cancellation - worker continued running after client disconnect/timeout
3. No per-request timeout - workers run indefinitely without checks
4. No heartbeat mechanism - daemon can't detect stuck workers

The worker continued executing for 2+ hours after the daemon timeout and client disconnect, producing 4632 chunks that were discarded.

---

## Implementation

### Phase 1: Protocol and Configuration

Added `timeout_seconds` field to `LoopRunRequest` and timeout/heartbeat config fields to `WorkerPoolConfig`:
- `request_timeout_seconds: int = 900` (15 min default)
- `heartbeat_interval_seconds: int = 30`
- `stuck_worker_timeout_seconds: int = 180`

**Files modified**:
- `packages/soothe/src/soothe/protocols/runner.py`
- `packages/soothe/src/soothe/config/daemon_config.py`
- `config/config.template.yml`
- `config/config.dev.yml`

### Phase 2: WorkerProcess and Worker Spawn

Added `cancel_event` and `last_heartbeat_at` fields to `WorkerProcess`:
- `cancel_event: multiprocessing.Event` - cooperative cancellation signal inherited at spawn
- `last_heartbeat_at: datetime | None` - timestamp tracking for stuck worker detection

Updated `_spawn_worker` to create and pass cancel_event to worker at spawn time.

**Files modified**:
- `packages/soothe/src/soothe/core/runner/pool_runner.py`

### Phase 3: Cooperative Cancellation and Timeout in Worker

Modified `_pool_worker` function:
- Accept `cancel_event`, `default_timeout_seconds`, `heartbeat_interval_seconds` args
- Clear cancel_event at start of each request
- Use `asyncio.timeout()` for overall request timeout
- Check `cancel_event.is_set()` between stream chunks for cooperative cancellation
- Send `("heartbeat", request_id, {"elapsed_seconds": elapsed})` periodically
- Send `("timeout", request_id, RuntimeError)` on TimeoutError
- Send `("cancelled", request_id, None)` when cancel detected

**Files modified**:
- `packages/soothe/src/soothe/core/runner/pool_runner.py`

### Phase 4: cancel_request and Poll Loop Updates

Implemented `cancel_request()` to set worker's cancel_event for cooperative cancellation.

Updated `_poll_worker_responses()`:
- Handle `"heartbeat"` messages → update worker.last_heartbeat_at
- Handle `"timeout"` messages → route RuntimeError to pending queue
- Handle `"cancelled"` messages → route CancelledError to pending queue
- Stuck worker detection: if no heartbeat for `stuck_worker_timeout_seconds`, call `_handle_stuck_worker`

Added `_handle_stuck_worker()` method to terminate stuck workers and respawn the slot.

Updated `_drain_abandoned_request()` to handle new message types (heartbeat, timeout, cancelled).

**Files modified**:
- `packages/soothe/src/soothe/core/runner/pool_runner.py`

### Phase 5: Embedding/Synthesis Timeout

Added async versions of similarity functions with timeout protection:
- `async_semantic_similarity()` - wraps model.encode() in thread pool with 30s timeout
- `async_calculate_relevance_score()` - async relevance scoring
- `async_rank_by_similarity()` - async ranking

Updated explore middleware to use async versions with 60s synthesis timeout and fallback to keyword similarity.

**Files modified**:
- `packages/soothe/src/soothe/utils/similarity.py`
- `packages/soothe/src/soothe/subagents/explore/middleware.py`

---

## Testing

Updated unit tests in `test_pool_runner.py` to include cancel_event parameter in WorkerProcess instantiations.

All 1605 unit tests pass.

---

## Summary

This enhancement adds:
1. **Cooperative cancellation**: Workers check cancel_event.is_set() between chunks
2. **Per-request timeout**: Workers enforce asyncio.timeout() on execution
3. **Heartbeat mechanism**: Workers send periodic pings, daemon detects stuck workers
4. **Explore timeout**: Embedding/synthesis calls have timeout protection with fallback

---

## Related

- RFC-221: Worker Pool Enhancement
- Commit that added `_route_failure_for_dead_busy_worker` (2a165df2)