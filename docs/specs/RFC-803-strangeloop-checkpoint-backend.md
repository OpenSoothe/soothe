# RFC-803: StrangeLoop Checkpoint Backend Architecture

**RFC**: 803
**Title**: StrangeLoop Checkpoint Backend Architecture
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-04-22
**Last Updated**: 2026-07-24
**Dependencies**: RFC-207 (Thread Lifecycle & Goal Context), RFC-218 (Checkpoint Tree), RFC-503 (Loop-First UX), RFC-801 (SQLite Runtime), RFC-802 (Persistence Architecture)
**Author**: Claude Sonnet 4.6
**Note**: Moved from 2xx (RFC-215) to 8xx persistence series per RFC-900 reclassification
**Design draft (SQLite flush parity)**: [2026-07-24-sqlite-runtime-isolation-performance-design.md](../drafts/2026-07-24-sqlite-runtime-isolation-performance-design.md)

---

## Abstract

This RFC defines the persistence backend architecture for StrangeLoop checkpoints with SQLite (primary) and PostgreSQL (secondary) support. The design enforces strict **thread/loop isolation**: thread data (CoreAgent Layer 1) and loop data (StrangeLoop Layer 2) are stored in separate directory structures with cross-reference linkage. SQLite provides simple local development, PostgreSQL offers production scalability with connection pooling and JSONB queries.

---

## Motivation

### Current Problem

**Mixed persistence** (current):
- StrangeLoop checkpoint: JSON file in `$SOOTHE_HOME/runs/{loop_id}/`
- CoreAgent checkpoint: LangGraph SQLite in thread-scoped location
- No standardized directory structure
- Thread/loop data mixed in same location
- No persistence backend flexibility (only SQLite)

### Proposed Solution

**Isolated persistence** with backend flexibility:
- Thread data: `$SOOTHE_HOME/data/threads/{thread_id}/` (CoreAgent Layer 1)
- Loop data: `$SOOTHE_HOME/data/loops/{loop_id}/` (StrangeLoop Layer 2)
- SQLite backend (primary): Per-loop database files
- PostgreSQL backend (secondary): Shared database with connection pool
- Clear separation: Thread vs loop data
- Cross-reference: Loop metadata references thread IDs

---

## Directory Structure

### Isolation Principle

**Key principle**: Thread folders contain **only CoreAgent data**, loop folders contain **only StrangeLoop data**. No data mixing.

```
SOOTHE_HOME/
  data/
    threads/  # CoreAgent thread runtime data (Layer 1)
      {thread_id}/
        checkpoint.db  # LangGraph SQLite checkpointer (managed by LangGraph)
        artifacts/  # Tool output spills, intermediate files
          manifest.json  # RunArtifactStore manifest
          tool_outputs/  # Spilled tool results
            tool_{tool_call_id}_{timestamp}.json
            tool_{tool_call_id}_{timestamp}_preview.txt
          reports/  # Final reports, large outputs
            final_report_{goal_id}_{timestamp}.md
            step_report_{step_id}_{timestamp}.md
          cache/  # Runtime caches
            system_prompt_cache.json
        history.jsonl  # Message history (optional, for quick replay)
        
    loops/  # StrangeLoop checkpoint data (Layer 2)
      {loop_id}/
        checkpoint.db  # StrangeLoop checkpoint database (SQLite)
        metadata.json  # Loop metadata (quick access, human-readable)
        working_memory/  # Working memory spills
          step-{goal_id}-{step_id}-{seq}.md
          manifest.json
```

**Cross-reference** (metadata.json):
```json
{
  "loop_id": "loop_abc123",
  "thread_ids": ["thread_001", "thread_002", "thread_003"],  // Reference to thread folders
  "current_thread_id": "thread_003",
  "status": "ready_for_next_goal",
  "total_goals_completed": 5,
  "total_thread_switches": 2,
  "schema_version": "3.1",
  "created_at": "2026-04-22T10:30:00Z",
  "updated_at": "2026-04-22T15:45:00Z"
}
```

---

## SQLite Backend (Primary)

### Schema Design

**Database location**: `$SOOTHE_DATA_DIR/databases/checkpoints.db` (RFC-801; shared process Runtime — not per-loop files)

**Access**: All reads/writes via `SqliteStoreRuntime` for that path. `StrangeLoopStateManager` MUST NOT open a private `sqlite3` connection to this file.

**Tables**:

#### agentloop_loops (metadata)
```sql
CREATE TABLE agentloop_loops (
    loop_id TEXT PRIMARY KEY,
    thread_ids TEXT NOT NULL,  -- JSON array: ["thread_001", "thread_002"]
    current_thread_id TEXT NOT NULL,
    status TEXT NOT NULL,  -- "running", "ready_for_next_goal", "finalized", "cancelled"
    total_goals_completed INTEGER DEFAULT 0,
    total_thread_switches INTEGER DEFAULT 0,
    human_message_count INTEGER NOT NULL DEFAULT 0,  -- incremented on accepted loop_input
    ai_message_count    INTEGER NOT NULL DEFAULT 0,  -- incremented on assistant-output ledger commit
    last_message_at TEXT,  -- ISO timestamp; NULL until first human or AI activity
    created_at TEXT NOT NULL,  -- ISO timestamp
    updated_at TEXT NOT NULL,  -- ISO timestamp
    schema_version TEXT DEFAULT '3.2'
);
```

**Message counters** track actual conversational activity at loop scope. `human_message_count` is incremented atomically when the daemon accepts a `loop_input` for the loop; `ai_message_count` is incremented atomically when the runner commits an assistant-output entry to the loop ledger (classified by `loop_message_assistant_output_phase`). Both counters MUST be updated by a single SQL statement together with `last_message_at` and `updated_at` (no read-modify-write). Both increments are best-effort: a failure is logged at `WARNING` and does not block the user-facing path.

**Activity timestamp.** `last_message_at` is the canonical activity clock. It is set ONLY by counter-increment statements; the `loop_new` RPC handler MUST NOT prime it. Empty-loop reclamation queries use `COALESCE(last_message_at, created_at)` so the idle clock begins at creation and resets on real activity.

PostgreSQL deployments SHOULD add a partial index to keep the empty-loop reclamation query cheap:

```sql
CREATE INDEX IF NOT EXISTS idx_agentloop_loops_empty
  ON agentloop_loops (last_message_at)
  WHERE human_message_count = 0 AND ai_message_count = 0;
```

#### checkpoint_anchors (synchronization)
```sql
CREATE TABLE checkpoint_anchors (
    anchor_id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    thread_id TEXT NOT NULL,  -- Cross-reference to thread folder
    checkpoint_id TEXT NOT NULL,  -- CoreAgent checkpoint_id
    checkpoint_ns TEXT DEFAULT '',
    anchor_type TEXT NOT NULL,  -- "iteration_start", "iteration_end", "failure_point"
    timestamp TEXT NOT NULL,  -- ISO timestamp
    
    -- Execution summary
    iteration_status TEXT,  -- "success", "failure", "partial"
    next_action_summary TEXT,
    tools_executed TEXT,  -- JSON array: ["tool_A", "tool_B"]
    reasoning_decision TEXT,
    
    FOREIGN KEY (loop_id) REFERENCES agentloop_loops(loop_id),
    UNIQUE(loop_id, iteration, anchor_type)
);

-- Indexes for efficient queries
CREATE INDEX idx_anchors_loop_iteration ON checkpoint_anchors(loop_id, iteration);
CREATE INDEX idx_anchors_thread ON checkpoint_anchors(thread_id);
CREATE INDEX idx_anchors_loop_thread ON checkpoint_anchors(loop_id, thread_id);
```

#### failed_branches (learning history)
```sql
CREATE TABLE failed_branches (
    branch_id TEXT PRIMARY KEY,  -- UUID
    loop_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    thread_id TEXT NOT NULL,  -- Cross-reference to thread folder
    root_checkpoint_id TEXT NOT NULL,
    failure_checkpoint_id TEXT NOT NULL,
    failure_reason TEXT NOT NULL,
    execution_path TEXT NOT NULL,  -- JSON array: ["checkpoint_A", ...]
    
    -- Pre-computed learning insights
    failure_insights TEXT,  -- JSON object
    avoid_patterns TEXT,  -- JSON array
    suggested_adjustments TEXT,  -- JSON array
    
    -- Metadata
    created_at TEXT NOT NULL,
    analyzed_at TEXT,  -- ISO timestamp
    pruned_at TEXT,  -- ISO timestamp (soft delete)
    
    FOREIGN KEY (loop_id) REFERENCES agentloop_loops(loop_id)
);

CREATE INDEX idx_branches_loop ON failed_branches(loop_id);
CREATE INDEX idx_branches_thread ON failed_branches(thread_id);
CREATE INDEX idx_branches_iteration ON failed_branches(loop_id, iteration);
```

#### goal_records (execution history)
```sql
CREATE TABLE goal_records (
    goal_id TEXT PRIMARY KEY,  -- "{loop_id}_goal_{seq}"
    loop_id TEXT NOT NULL,
    goal_text TEXT NOT NULL,
    thread_id TEXT NOT NULL,  -- Cross-reference
    iteration INTEGER NOT NULL,
    status TEXT NOT NULL,  -- "completed", "failed", "cancelled"
    
    -- Execution traces
    reason_history TEXT,  -- JSON array
    act_history TEXT,  -- JSON array
    
    -- Output
    final_report TEXT,
    evidence_summary TEXT,
    
    -- Metrics
    duration_ms INTEGER DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    
    -- Timestamps
    started_at TEXT NOT NULL,
    completed_at TEXT,
    
    FOREIGN KEY (loop_id) REFERENCES agentloop_loops(loop_id)
);

CREATE INDEX idx_goals_loop ON goal_records(loop_id);
CREATE INDEX idx_goals_thread ON goal_records(thread_id);
```

---

## PostgreSQL Backend (Secondary)

### Schema Design

**Connection**: Async connection pool via `AsyncPostgresSaver` (LangGraph compatible)

**Schema**: Same as SQLite with PostgreSQL-specific optimizations:

```sql
-- PostgreSQL-specific optimizations
CREATE TABLE checkpoint_anchors (
    -- Same columns as SQLite
    iteration INTEGER NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    
    PRIMARY KEY (anchor_id),
    UNIQUE(loop_id, iteration, anchor_type)
);

-- GiST index for timestamp range queries (failure analysis)
CREATE INDEX idx_anchors_timestamp_range ON checkpoint_anchors USING GiST (timestamp);

-- Partial index for failed branches (skip pruned)
CREATE INDEX idx_branches_active ON failed_branches(loop_id, iteration) WHERE pruned_at IS NULL;

-- JSONB columns for structured data (better query performance)
ALTER TABLE failed_branches 
    ALTER COLUMN execution_path TYPE JSONB USING execution_path::jsonb,
    ALTER COLUMN failure_insights TYPE JSONB USING failure_insights::jsonb,
    ALTER COLUMN avoid_patterns TYPE JSONB USING avoid_patterns::jsonb;

-- Enable JSONB queries for failure pattern analysis
CREATE INDEX idx_branches_patterns ON failed_branches USING Gin (avoid_patterns);
CREATE INDEX idx_branches_insights ON failed_branches USING Gin (failure_insights);
```

---

## Persistence Manager API

### Core Interface

```python
class StrangeLoopCheckpointPersistenceManager:
    """Manager for StrangeLoop checkpoint persistence.
    
    Supports SQLite (primary) and PostgreSQL (secondary) backends.
    Enforces thread/loop isolation with cross-reference linkage.
    """

    def __init__(self, backend: Literal["sqlite", "postgresql"], soothe_home: Path):
        """Initialize persistence manager.
        
        Args:
            backend: Database backend type.
            soothe_home: Base directory for checkpoint storage.
        """
        self.backend = backend
        self.soothe_home = soothe_home
        
        # Isolated directories
        self.threads_dir = soothe_home / "data" / "threads"
        self.loops_dir = soothe_home / "data" / "loops"
        
        # Ensure directories exist
        self.threads_dir.mkdir(parents=True, exist_ok=True)
        self.loops_dir.mkdir(parents=True, exist_ok=True)
        
        if backend == "postgresql":
            self.pool = self._init_postgres_pool()

    def get_thread_checkpoint_path(self, thread_id: str) -> Path:
        """Get CoreAgent thread checkpoint database path.
        
        Returns:
            Path to thread's checkpoint.db (managed by LangGraph).
        """
        return self.threads_dir / thread_id / "checkpoint.db"

    def get_thread_artifacts_dir(self, thread_id: str) -> Path:
        """Get CoreAgent thread artifacts directory.
        
        Returns:
            Path to thread's artifacts/ directory.
        """
        return self.threads_dir / thread_id / "artifacts"

    def get_loop_checkpoint_path(self, loop_id: str) -> Path:
        """Get StrangeLoop checkpoint database path.
        
        Returns:
            Path to loop's checkpoint.db (managed by StrangeLoop).
        """
        return self.loops_dir / loop_id / "checkpoint.db"

    def get_loop_working_memory_dir(self, loop_id: str) -> Path:
        """Get StrangeLoop working memory spill directory.
        
        Returns:
            Path to loop's working_memory/ directory.
        """
        return self.loops_dir / loop_id / "working_memory"
```

### Checkpoint Anchor Operations

```python
async def save_checkpoint_anchor(
    self,
    loop_id: str,
    iteration: int,
    thread_id: str,
    checkpoint_id: str,
    anchor_type: str,
    execution_summary: dict[str, Any] | None = None,
) -> None:
    """Save iteration checkpoint anchor with thread cross-reference.
    
    Args:
        loop_id: StrangeLoop identifier.
        iteration: Iteration number.
        thread_id: Thread where checkpoint belongs (cross-reference).
        checkpoint_id: CoreAgent checkpoint_id.
        anchor_type: "iteration_start", "iteration_end", "failure_point".
        execution_summary: Optional execution metadata.
    """
    pass

async def get_checkpoint_anchors_for_range(
    self,
    loop_id: str,
    start_iteration: int,
    end_iteration: int,
) -> list[dict[str, Any]]:
    """Get checkpoint anchors for iteration range (failure analysis).
    
    Returns:
        List of anchors with thread_id cross-references.
    """
    pass

async def get_thread_checkpoints_for_loop(
    self,
    loop_id: str,
) -> dict[str, list[str]]:
    """Get all thread checkpoint_ids for a loop (cross-reference map).
    
    Returns:
        Dict: {thread_id: [checkpoint_id_1, checkpoint_id_2, ...]}
    """
    pass
```

### Failed Branch Operations

```python
async def save_failed_branch(
    self,
    branch_id: str,
    loop_id: str,
    iteration: int,
    thread_id: str,
    root_checkpoint_id: str,
    failure_checkpoint_id: str,
    failure_reason: str,
    execution_path: list[str],
) -> None:
    """Save failed branch with thread cross-reference.
    
    Args:
        thread_id: Thread where failure occurred (cross-reference).
    """
    pass

async def update_branch_analysis(
    self,
    branch_id: str,
    loop_id: str,
    failure_insights: dict[str, Any],
    avoid_patterns: list[str],
    suggested_adjustments: list[str],
) -> None:
    """Update branch with pre-computed learning insights."""
    pass

async def get_failed_branches_for_loop(
    self,
    loop_id: str,
    include_pruned: bool = False,
) -> list[FailedBranchRecord]:
    """Get all failed branches for loop (history reconstruction)."""
    pass

async def prune_old_branches(
    self,
    loop_id: str,
    retention_days: int = 30,
) -> int:
    """Prune old branches (soft delete with pruned_at timestamp).
    
    Returns:
        Number of branches pruned.
    """
    pass
```

### Load/Save Operations

```python
async def load_checkpoint_tree_ref(
    self,
    loop_id: str,
) -> CoreAgentCheckpointTreeRef:
    """Load complete checkpoint tree for StrangeLoop.
    
    Returns:
        CoreAgentCheckpointTreeRef with main_line + failed_branches.
    """
    pass

async def load_sloop_checkpoint(
    self,
    loop_id: str,
) -> StrangeLoopCheckpoint:
    """Load StrangeLoop checkpoint from persistence backend.
    
    Process:
    1. Load metadata.json (quick access)
    2. Load checkpoint.db (checkpoint tree, goal records)
    3. Load CoreAgent checkpoint refs (metadata linkage)
    
    Returns:
        Complete StrangeLoopCheckpoint v3.1.
    """
    pass

async def save_sloop_checkpoint(
    self,
    checkpoint: StrangeLoopCheckpoint,
) -> None:
    """Save StrangeLoop checkpoint to persistence backend.
    
    Process:
    1. Save metadata.json (human-readable quick access)
    2. Save checkpoint.db (checkpoint tree, goal records)
    3. Update CoreAgent checkpoint refs (metadata linkage)
    """
    pass
```

---

## Configuration Integration

### SootheConfig Extension

```python
# config/config.yml
sloop_checkpoint:
  persistence_backend: "sqlite"  # "sqlite" or "postgresql"
  
  sqlite:
    db_dir: "$SOOTHE_HOME/data/loops"  # Per-loop database files
    
  postgresql:
    connection_pool_size: 10
    # Uses existing SootheConfig postgres settings
    
  retention:
    failed_branch_retention_days: 30
    checkpoint_anchor_retention_days: 90
    goal_record_retention_days: 180
```

---

## Implementation Tasks

### Phase 1: Directory Structure
- Create `$SOOTHE_HOME/data/threads/` directory
- Create `$SOOTHE_HOME/data/loops/` directory
- Ensure isolation enforcement

### Phase 2: SQLite Backend
- Create per-loop database schema
- Implement persistence manager (SQLite operations)
- Integrate with StrangeLoop checkpoint save/load

### Phase 3: PostgreSQL Backend
- Create PostgreSQL schema with optimizations
- Implement persistence manager (PostgreSQL operations)
- Add connection pool integration

### Phase 4: Cross-Reference Management
- Implement thread_id cross-reference queries
- Implement checkpoint_id linkage queries
- Implement CoreAgent checkpoint path resolution

### Phase 5: Retention & Cleanup
- Implement branch pruning policy
- Implement anchor cleanup policy
- Implement goal record cleanup policy
- Implement empty-loop reclamation (see *Empty-Loop Reclamation* below)

---

## Empty-Loop Reclamation

A loop with `human_message_count = 0 AND ai_message_count = 0 AND status != 'running'` and `COALESCE(last_message_at, created_at)` older than the configured idle window is reclaimable: it represents a bootstrap session that never produced a human/AI exchange (typical cause: a client tab opened and closed without input).

Reclamation is performed by the same periodic daemon task that purges expired ephemeral loops (RFC-450 §loop_gc). The task runs two listing queries per tick — expired-ephemeral and empty-idle — de-duplicates by `loop_id`, and invokes the existing per-loop purge helper which removes the DB row, the on-disk loop directory, and any cross-referenced execution data.

Two independent idle thresholds gate the two passes:

| Threshold | Applies to | Default |
|---|---|---|
| `ephemeral_idle_hours` | `is_ephemeral = 1` rows (any state) | unchanged |
| `empty_idle_hours` | rows with both counters zero | 24 hours |

A loop that is both ephemeral and empty is reclaimed by whichever pass fires first. The 24h empty-loop default gives a fresh tab a working day to receive input before reclamation.

Per-row purge failures are isolated (try/except) so a single failure does not abort the batch. The race where an increment lands between the listing query and the purge call is bounded by the idle window (hours) and is acceptable; implementations MAY add a final `WHERE human_message_count = 0 AND ai_message_count = 0` guard to the purge SQL if observed in practice.

---

## Asynchronous Checkpoint Writing (Phase 6)

### Motivation

Performance analysis of production loops shows checkpoint writes occurring at critical points:
- Step completion triggers checkpoint finalize, causing latency spikes (8.47s → 19.05s)
- Each checkpoint write blocks the calling coroutine (~16ms for SQLite, ~20-30ms for PostgreSQL)
- Metadata sync adds additional filesystem IO overhead

**Problem**: Synchronous checkpoint writes introduce blocking delays in the execution path, particularly at step boundaries where latency peaks occur.

### Design: Fire-and-Forget with Periodic Flush

**Principle**: Checkpoint writes are non-blocking for the caller, with periodic forced writes to bound data loss risk.

```python
class StrangeLoopStateManager:
    _async_write_enabled: bool = True
    _pending_saves: asyncio.Queue[StrangeLoopCheckpoint] | None = None
    _flush_worker: asyncio.Task | None = None
    _flush_interval: float = 5.0  # seconds
    _last_save_checkpoint: StrangeLoopCheckpoint | None = None  # Local cache
    
    async def _save_checkpoint_to_db(self, checkpoint: StrangeLoopCheckpoint) -> None:
        """Save checkpoint asynchronously (non-blocking when enabled).
        
        Process:
        1. Update local cache immediately (ensures subsequent reads get latest)
        2. Enqueue for async write (fire-and-forget)
        3. Metadata sync also deferred
        
        Args:
            checkpoint: Checkpoint to save.
        """
        checkpoint.updated_at = datetime.now(UTC)
        
        # Immediate local cache update (no blocking)
        self._checkpoint = checkpoint
        self._last_save_checkpoint = checkpoint
        
        if self._async_write_enabled and self._pending_saves:
            # Async mode: enqueue for background write
            await self._pending_saves.put(checkpoint)
            logger.debug("Enqueued async checkpoint save: loop=%s", self.loop_id)
        else:
            # Sync mode (fallback): direct write
            await self._do_save_checkpoint(checkpoint)
            self._sync_metadata_to_disk()
    
    async def _start_flush_worker(self) -> None:
        """Start background worker for periodic checkpoint flushes."""
        if self._flush_worker is not None:
            return
        
        self._pending_saves = asyncio.Queue(maxsize=100)
        self._flush_worker = asyncio.create_task(self._flush_worker_loop())
        logger.info("Async checkpoint worker started: loop=%s flush_interval=%ss", 
                    self.loop_id, self._flush_interval)
    
    async def _flush_worker_loop(self) -> None:
        """Background loop that flushes queued checkpoints."""
        while True:
            try:
                # Wait for either:
                # 1. New checkpoint in queue
                # 2. Flush interval timeout (force periodic write)
                checkpoint = await asyncio.wait_for(
                    self._pending_saves.get(), 
                    timeout=self._flush_interval
                )
                await self._do_save_checkpoint(checkpoint)
                await asyncio.to_thread(self._sync_metadata_to_disk)
                
            except asyncio.TimeoutError:
                # Periodic flush: ensure latest checkpoint is persisted
                if self._last_save_checkpoint:
                    await self._do_save_checkpoint(self._last_save_checkpoint)
                    await asyncio.to_thread(self._sync_metadata_to_disk)
                    logger.debug("Periodic checkpoint flush: loop=%s", self.loop_id)
                    
            except asyncio.CancelledError:
                # Final flush on shutdown
                if self._last_save_checkpoint:
                    await self._do_save_checkpoint(self._last_save_checkpoint)
                logger.info("Async checkpoint worker stopped: loop=%s", self.loop_id)
                raise
                
            except Exception as e:
                logger.error("Async checkpoint write failed: %s", e)
                # Continue loop - periodic flush will retry
    
    async def _do_save_checkpoint(self, checkpoint: StrangeLoopCheckpoint) -> None:
        """Perform actual checkpoint write (called by worker or sync fallback)."""
        if self._backend_type == "postgresql":
            await self._ensure_backend_initialized()
            await self._postgres_backend.save_checkpoint(checkpoint)
        else:
            conn = await self._ensure_writer_connection()
            await asyncio.to_thread(self._save_checkpoint_sync, conn, checkpoint)
    
    async def force_flush(self) -> None:
        """Force immediate checkpoint write (for critical operations).
        
        Used by:
        - finalize_loop (must persist final state)
        - archive_and_finalize (must persist before archive)
        - close (must persist before shutdown)
        """
        if self._last_save_checkpoint:
            await self._do_save_checkpoint(self._last_save_checkpoint)
            await asyncio.to_thread(self._sync_metadata_to_disk)
            logger.info("Force checkpoint flush: loop=%s", self.loop_id)
    
    async def close(self) -> None:
        """Close backend with final checkpoint flush."""
        # Force final flush
        await self.force_flush()
        
        # Cancel worker
        if self._flush_worker:
            self._flush_worker.cancel()
            try:
                await self._flush_worker
            except asyncio.CancelledError:
                pass
            self._flush_worker = None
        
        # Close connections (existing code)
        # ...
```

### Configuration

```yaml
# config/config.yml
agent:
  loop:
    checkpoint:
      async_write: true        # Enable fire-and-forget writes
      flush_interval: 5.0       # Periodic forced write interval (seconds)
      queue_size: 100           # Max queued checkpoints before blocking
```

### Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Crash data loss | Periodic flush (5s default) bounds loss window |
| Queue overflow | Max queue size (100) prevents memory bloat; blocks when full |
| Write failure | Background retry; periodic flush retries latest checkpoint |
| Ordering issues | Queue is FIFO; single worker ensures serialization |

### Expected Performance Impact

| Metric | Before | After |
|--------|--------|-------|
| Step completion latency | 19.05s | ~7s (checkpoint non-blocking) |
| Peak latency reduction | N/A | **~12s** |
| Per-save blocking time | 16ms | 0ms (async) |
| Crash recovery window | 0 (sync) | 5s (configurable) |

### When to Use Sync Mode

Disable async writes for:
- Single-goal loops (overhead outweighs benefit)
- Debug/diagnostic runs (want exact checkpoint timing)
- Low-latency environments (network IO is primary bottleneck)

**PostgreSQL note**: When `persistence.default_backend=postgresql` and the unified writer is enabled (IG-550), per-loop `_flush_worker_loop` is **not** used for checkpoint writes. See §Unified Write Pipeline below.

**SQLite note**: When `persistence.default_backend=sqlite`, per-loop flush workers and per-manager private `sqlite3` writer/reader pools are **forbidden**. Checkpoint I/O uses the process-scoped `checkpoints.db` `SqliteStoreRuntime` (RFC-801) with one coalescing flush worker bound to that Runtime (same control-plane shape as `LoopPersistenceWriter`). See §Unified Write Pipeline — SQLite amendment below.

---

## Unified Write Pipeline (Amendment — IG-550 / IG-571)

### Motivation

RFC-803 Phase 6 described per-`StrangeLoopStateManager` async flush workers (FIFO queue, per-request lifecycle). Production thread_pool mode runs **many concurrent loops in one process**, each on a **dedicated worker-thread event loop**. Goals also share one PostgreSQL database (`soothe_checkpoints`) via `SharedPostgreSQLPool` / `PostgresPoolRegistry` (IG-561).

Per-loop flush workers cause:

- Start/stop churn every request (no sustained coalescing)
- Duplicate write pipelines (StrangeLoop + ContextEngine + goal tail)
- Goal-boundary races (finalize + `close()` on separate flush paths)

IG-550 introduced a process-scoped **`LoopPersistenceWriter`** for coalesced writes and single-transaction goal boundaries. IG-571 completes the execution model for thread_pool.

### Layered responsibilities

| Layer | Component | Scope | Responsibility |
|-------|-----------|-------|----------------|
| Domain | `StrangeLoopStateManager` | per `loop_id` | Checkpoint model, in-memory cache, load/merge, finalize semantics, bounded `close` |
| Write pipeline | `LoopPersistenceWriter` | per process | Latest-wins coalesce, durable flush, `persist_goal_boundary`, CE dag/ledger submits |
| Connections | `SharedPostgreSQLPool` | per process | `AsyncConnectionPool` to `soothe_checkpoints`; borrowed by writer and read backends |

**Reads** stay on the caller loop via `PostgreSQLPersistenceBackend` + shared pool. **Writes** go through the writer submit API.

### Data flow

```text
StrangeLoopStateManager ──┐
ContextEngine (PG) ───────┼──► submit_* ──► LoopPersistenceWriter (main loop) ──► SharedPostgreSQLPool
Goal completion tail ─────┘
```

### Write modes

| Mode | Trigger | Behavior |
|------|---------|----------|
| Background | `record_iteration`, iteration `save()` | `submit_enqueue` — latest-wins coalesce; flush on `flush_interval` |
| Durable | Goal boundary, `close()` | `submit_flush_durable` / `submit_persist_goal_boundary` — single transaction where possible |
| Release | `state_manager.close()` | `submit_release_loop` — bounded drain; mark loop released in writer |

Hot/cold split (IG-550 Phase 3): iteration writes may update index only; full blob at goal boundary.

### Execution model (thread_pool — IG-571)

**Invariant**: `LoopPersistenceWriter` asyncio tasks and loop-scoped locks run **only on the daemon main event loop**.

Worker-thread loops MUST NOT call `await writer.enqueue_checkpoint()` directly. They call thread-safe **`submit_*`** methods that schedule work on the main loop (e.g. `asyncio.run_coroutine_threadsafe`).

Cross-thread pending-map mutations use **`threading.Lock`**. DB serialization uses **`asyncio.Lock`** on the main loop only.

**Failure mode (pre-IG-571)**: `asyncio.Lock` on a process singleton called from worker loops raises `RuntimeError: … bound to a different event loop`, failing goal init/close and killing thread workers.

**Safe failure (post-IG-571)**: When the writer is active, PostgreSQL checkpoint writes go **only** through `LoopPersistenceWriter`. On durable failure, return `PersistResult.ok=False` and call `mark_persist_degraded()` — **no** bypass to `_do_save_checkpoint()`.

**SQLite (post–RFC-801 Runtime amendment, 2026-07-24)**: SQLite MUST NOT keep the historical bypass of “`writer is None` → per-manager `_do_save_checkpoint` with a private connection.” Instead:

| Layer | Component | Scope | Responsibility |
|-------|-----------|-------|----------------|
| Domain | `StrangeLoopStateManager` | per `loop_id` | Checkpoint model, in-memory cache, load/merge, enqueue coalesced state |
| Write pipeline | Process-scoped flush bound to `SqliteStoreRuntime` for `databases/checkpoints.db` | per process | Latest-wins coalesce, durable flush, shutdown drain |
| Connections | `SqliteStoreRuntime` / `SqliteRuntimeRegistry` | per DB file | Single writer, leased readers, `BEGIN IMMEDIATE`, WAL + busy_timeout |

Managers MUST NOT open private writer/reader pools on `checkpoints.db`. Reads and writes go through the shared Runtime (`run_read` / `run_write`). Cross-file CE/display updates remain separate Runtimes (ordered best-effort), matching multi-DB PostgreSQL non-atomicity.

### SQLite data flow

```text
StrangeLoopStateManager ──┐
  (coalesced pending)     ├──► process flush (checkpoints Runtime) ──► databases/checkpoints.db
Context / display / … ────┘    (separate Runtimes per RFC-801 files)
```

### Execution model (worker_pool)

Each subprocess has one event loop. Writer singleton is per process; initialize on that loop at worker startup. Submit bridge is optional; direct `await` on writer methods is safe when caller and writer share the same loop.

### Pool reset protocol

Before `SharedPostgreSQLPool.reset_pool()`:

1. `writer.pause_for_pool_reset()` — stop accepts, drain in-flight
2. Close old pool
3. Rebind registry pool; `writer.resume_after_pool_reset()`

Never close the pool while a main-loop flush task holds connections.

### Configuration

Extends Phase 6 checkpoint config (IG-550):

```yaml
agent:
  loop:
    checkpoint:
      async_write: true
      flush_interval: 5.0
      coalesce: true
      close_timeout_seconds: 30
      durable_flush_timeout: 10
```

`persistence.checkpoints_pool_size` (IG-561) caps shared pool size; writer does not add a separate pool.

### Success criteria (amendment)

1. No `bound to a different event loop` from writer under max thread_pool concurrency
2. Goal boundary: checkpoint + CE tables consistent within durable flush timeout (PostgreSQL single-DB transaction; SQLite best-effort across Runtimes per RFC-801)
3. `close()` bounded by `close_timeout_seconds` (not outer request timeout)
4. Process connection count to `soothe_checkpoints` ≤ configured pool cap (PostgreSQL)
5. SQLite: one `SqliteStoreRuntime` for `databases/checkpoints.db`; zero per-manager private write connections; process-scoped coalesce flush only

### Related implementation guides

- [IG-550](../impl/IG-550-high-performance-persistence.md) — writer introduction, coalescing, goal-boundary transaction
- [IG-571](../impl/IG-571-main-loop-persistence-writer-bridge.md) — main-loop submit bridge (thread_pool fix)
- [RFC-801](./RFC-801-sqlite-backend.md) — `SqliteStoreRuntime` / `databases/` layout
- Design draft: [2026-07-24-sqlite-runtime-isolation-performance-design.md](../drafts/2026-07-24-sqlite-runtime-isolation-performance-design.md)

---

## Success Criteria

1. Thread/loop isolation enforced ✓
2. SQLite backend works via process-scoped `databases/checkpoints.db` Runtime (RFC-801) ✓
3. PostgreSQL backend works (connection pool) ✓
4. Cross-reference queries work (thread_id → checkpoint_ids) ✓
5. Checkpoint anchors saved correctly ✓
6. Failed branches saved with execution_path ✓
7. Learning insights stored and retrieved ✓
8. Retention policies work (pruning) ✓
9. Metadata.json provides quick access ✓
10. No data duplication ✓
11. **Async checkpoint writes reduce peak latency by ~12s** ✓ (Phase 6)
12. **Unified write pipeline: no cross-event-loop writer errors under thread_pool** (IG-571)

---

## Related Specifications

- RFC-218: StrangeLoop Checkpoint Tree Architecture
- RFC-207: StrangeLoop Thread Lifecycle & Goal Context (supersedes RFC-216)
- RFC-503: Loop-First User Experience
- RFC-411: Event Stream Replay
- RFC-801: SQLite Backend / `SqliteStoreRuntime`
- RFC-802: Persistence Architecture Refactor (`databases/` layout)
- IG-550: High-Performance Persistence Optimization (unified writer)
- IG-571: Main-Loop Persistence Writer Bridge (thread_pool execution model)
- Design draft: [2026-07-24-sqlite-runtime-isolation-performance-design.md](../drafts/2026-07-24-sqlite-runtime-isolation-performance-design.md)

---

## Change History

| Date | Change |
|------|--------|
| 2026-04-22 | Initial Draft (as RFC-215) |
| 2026-06-04 | Reclassified as RFC-803 |
| 2026-07-08 | Unified write pipeline amendment (IG-550 / IG-571) |
| 2026-07-24 | SQLite process-scoped Runtime + flush parity; `databases/checkpoints.db` hard cut (RFC-801) |

---

**End of RFC-803 Draft**
