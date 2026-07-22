# IG-523: Async Checkpoint Writing Implementation

**IG**: 523
**Title**: Async Checkpoint Writing for StrangeLoop
**Status**: In Progress
**Created**: 2026-06-28
**RFC**: RFC-803 Phase 6
**Author**: Claude Opus 4.8
**Dependencies**: IG-055 (PostgreSQL backend), IG-258 (Connection pooling)

---

## Background

Performance analysis of loop 87cf revealed checkpoint-related latency spikes:
- Step completion latency: 8.47s → 19.05s (+10.6s)
- Checkpoint writes blocking at critical step boundaries
- 23 checkpoint save events during 6-hour run

**Root Cause**: Synchronous checkpoint writes block execution at step completion points.

**Solution**: Fire-and-forget async writes with periodic forced flush.

---

## Scope

### In Scope
1. Async checkpoint write queue in `StrangeLoopStateManager`
2. Background flush worker with configurable interval
3. Configuration options for async mode
4. `force_flush()` API for critical operations
5. Graceful shutdown handling

### Out of Scope
- Incremental/delta writes (future optimization)
- Checkpoint compression
- Batch writes across multiple loops

---

## Implementation Plan

### Phase 1: Configuration Schema

**File**: `packages/soothe/src/soothe/config/models.py`

Add checkpoint config to `LoopConcurrencyConfig`:

```python
class LoopCheckpointConfig(BaseModel):
    """StrangeLoop checkpoint persistence configuration (RFC-803 Phase 6)."""
    
    async_write: bool = Field(
        default=True,
        description="Enable fire-and-forget checkpoint writes (non-blocking)",
    )
    
    flush_interval: float = Field(
        default=5.0,
        ge=1.0,
        le=60.0,
        description="Periodic forced write interval (seconds). Bounds crash data loss.",
    )
    
    queue_size: int = Field(
        default=100,
        ge=10,
        le=500,
        description="Max queued checkpoints before blocking caller",
    )
```

Update config template: `config/config.template.yml`

---

### Phase 2: StrangeLoopStateManager Async Queue

**File**: `packages/soothe/src/soothe/sloop/state/sloop_manager.py`

#### Changes to `StrangeLoopStateManager.__init__`:

```python
def __init__(
    self,
    loop_id: str | None = None,
    workspace: Path | None = None,
    reader_pool_size: int = 5,
    config: SootheConfig | None = None,
    shared_pool: SharedPostgreSQLPool | None = None,
) -> None:
    # ... existing init code ...
    
    # Async checkpoint config (RFC-803 Phase 6)
    checkpoint_cfg = config.agent.loop.concurrency.checkpoint if config else None
    self._async_write_enabled = checkpoint_cfg.async_write if checkpoint_cfg else True
    self._flush_interval = checkpoint_cfg.flush_interval if checkpoint_cfg else 5.0
    self._queue_size = checkpoint_cfg.queue_size if checkpoint_cfg else 100
    
    # Async write infrastructure
    self._pending_saves: asyncio.Queue[StrangeLoopCheckpoint] | None = None
    self._flush_worker: asyncio.Task | None = None
    self._last_save_checkpoint: StrangeLoopCheckpoint | None = None
    self._worker_started = False
```

#### New Methods:

1. `_start_flush_worker()` - Initialize async queue and worker task
2. `_flush_worker_loop()` - Background loop for queued writes
3. `_do_save_checkpoint()` - Actual backend write (extracted from existing)
4. `force_flush()` - Force immediate write for critical operations
5. `_stop_flush_worker()` - Graceful shutdown with final flush

#### Modified `_save_checkpoint_to_db()`:

```python
async def _save_checkpoint_to_db(self, checkpoint: StrangeLoopCheckpoint) -> None:
    """Save checkpoint asynchronously (non-blocking when enabled)."""
    checkpoint.updated_at = datetime.now(UTC)
    
    # Immediate local cache update
    self._checkpoint = checkpoint
    self._last_save_checkpoint = checkpoint
    
    if self._async_write_enabled:
        # Start worker if not running
        if not self._worker_started:
            await self._start_flush_worker()
        
        # Enqueue (non-blocking if queue not full)
        try:
            self._pending_saves.put_nowait(checkpoint)
            logger.debug("Enqueued async checkpoint: loop=%s", self.loop_id)
        except asyncio.QueueFull:
            # Queue full - fallback to sync write
            logger.warning("Checkpoint queue full, sync write fallback: loop=%s", self.loop_id)
            await self._do_save_checkpoint(checkpoint)
            await asyncio.to_thread(self._sync_metadata_to_disk)
    else:
        # Sync mode (existing behavior)
        await self._do_save_checkpoint(checkpoint)
        self._sync_metadata_to_disk()
```

---

### Phase 3: Critical Operations Override

**Methods requiring `force_flush()` before proceeding:**

1. `finalize_loop()` - Final state must persist
2. `archive_and_finalize()` - Archive needs latest checkpoint
3. `close()` - Shutdown needs final write

```python
async def finalize_loop(self, status: str) -> None:
    if self._checkpoint is None:
        return
    
    self._checkpoint.status = status
    # Use force_flush for critical operations
    await self.force_flush()
    
    logger.info("Finalized loop %s (status: %s)", self.loop_id, status)

async def close(self) -> None:
    # Force final flush before closing
    await self.force_flush()
    
    # Stop worker
    if self._flush_worker:
        self._flush_worker.cancel()
        try:
            await self._flush_worker
        except asyncio.CancelledError:
            pass
    
    # ... existing close code ...
```

---

### Phase 4: Unit Tests

**File**: `packages/soothe/tests/unit/foundation/sloop/state/test_async_checkpoint.py`

#### Test Cases:

1. `test_async_write_enqueues_checkpoint` - Verify queue behavior
2. `test_flush_worker_processes_queue` - Worker loop functionality
3. `test_periodic_flush_on_timeout` - Flush interval behavior
4. `test_force_flush_immediate_write` - Critical operations
5. `test_queue_full_fallback_sync` - Overflow handling
6. `test_graceful_shutdown_with_final_flush` - Close behavior
7. `test_async_disabled_uses_sync` - Config override

---

### Phase 5: Integration Testing

**File**: `tests/integration/test_loop_async_checkpoint.py`

#### Test Scenarios:

1. Long-running loop with many checkpoints - Verify no latency spike
2. Simulated crash recovery - Verify periodic flush bounds loss
3. Concurrent loops with async checkpoint - Verify isolation
4. PostgreSQL backend async behavior - Verify network IO non-blocking

---

## Verification Checklist

- [ ] Configuration schema added to `models.py`
- [ ] Config template updated
- [ ] `StrangeLoopStateManager` async queue implemented
- [ ] `_save_checkpoint_to_db()` modified for async
- [ ] `force_flush()` added for critical operations
- [ ] `close()` handles graceful shutdown
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] No regression in existing checkpoint tests
- [ ] Latency improvement verified via log analysis

---

## Expected Outcome

| Metric | Before | After |
|--------|--------|-------|
| Step completion peak latency | 19.05s | ~7s |
| Checkpoint write blocking | 16ms | 0ms |
| Crash data loss window | 0 | 5s max |

---

## Rollback Plan

If async checkpoint causes issues:
1. Set `async_write: false` in config
2. System reverts to sync mode (existing behavior)
3. No code changes needed

---

## References

- RFC-803 Phase 6 (new section)
- RFC-207 (StrangeLoop lifecycle)
- IG-055 (PostgreSQL backend)
- IG-258 (Connection pooling)
- Performance analysis: `docs/analysis/async-checkpoint-deep-analysis.md`