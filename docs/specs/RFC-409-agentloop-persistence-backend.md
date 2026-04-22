# AgentLoop Persistence Backend Architecture

> Design draft for SQLite/PostgreSQL persistence backend with thread/loop isolation.
>
> **RFC Number**: RFC-409
> **Status**: Draft
> **Created**: 2026-04-22
> **Dependencies**: RFC-608 (Multi-Thread Lifecycle), RFC-611 (Checkpoint Tree), RFC-503 (Loop-First UX)
> **Author**: Claude Sonnet 4.6

---

## Abstract

This RFC defines the persistence backend architecture for AgentLoop checkpoints with SQLite (primary) and PostgreSQL (secondary) support. The design enforces strict **thread/loop isolation**: thread data (CoreAgent Layer 1) and loop data (AgentLoop Layer 2) are stored in separate directory structures with cross-reference linkage. SQLite provides simple local development, PostgreSQL offers production scalability with connection pooling and JSONB queries.

---

## Motivation

### Current Problem

**Mixed persistence** (current):
- AgentLoop checkpoint: JSON file in `$SOOTHE_HOME/runs/{loop_id}/`
- CoreAgent checkpoint: LangGraph SQLite in thread-scoped location
- No standardized directory structure
- Thread/loop data mixed in same location
- No persistence backend flexibility (only SQLite)

### Proposed Solution

**Isolated persistence** with backend flexibility:
- Thread data: `$SOOTHE_HOME/data/threads/{thread_id}/` (CoreAgent Layer 1)
- Loop data: `$SOOTHE_HOME/data/loops/{loop_id}/` (AgentLoop Layer 2)
- SQLite backend (primary): Per-loop database files
- PostgreSQL backend (secondary): Shared database with connection pool
- Clear separation: Thread vs loop data
- Cross-reference: Loop metadata references thread IDs

---

## Directory Structure

### Isolation Principle

**Key principle**: Thread folders contain **only CoreAgent data**, loop folders contain **only AgentLoop data**. No data mixing.

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
        
    loops/  # AgentLoop checkpoint data (Layer 2)
      {loop_id}/
        checkpoint.db  # AgentLoop checkpoint database (SQLite)
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

**Database location**: `$SOOTHE_HOME/data/loops/{loop_id}/checkpoint.db`

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
    created_at TEXT NOT NULL,  -- ISO timestamp
    updated_at TEXT NOT NULL,  -- ISO timestamp
    schema_version TEXT DEFAULT '3.1'
);
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
class AgentLoopCheckpointPersistenceManager:
    """Manager for AgentLoop checkpoint persistence.
    
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
        """Get AgentLoop checkpoint database path.
        
        Returns:
            Path to loop's checkpoint.db (managed by AgentLoop).
        """
        return self.loops_dir / loop_id / "checkpoint.db"

    def get_loop_working_memory_dir(self, loop_id: str) -> Path:
        """Get AgentLoop working memory spill directory.
        
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
        loop_id: AgentLoop identifier.
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
    """Load complete checkpoint tree for AgentLoop.
    
    Returns:
        CoreAgentCheckpointTreeRef with main_line + failed_branches.
    """
    pass

async def load_agentloop_checkpoint(
    self,
    loop_id: str,
) -> AgentLoopCheckpoint:
    """Load AgentLoop checkpoint from persistence backend.
    
    Process:
    1. Load metadata.json (quick access)
    2. Load checkpoint.db (checkpoint tree, goal records)
    3. Load CoreAgent checkpoint refs (metadata linkage)
    
    Returns:
        Complete AgentLoopCheckpoint v3.1.
    """
    pass

async def save_agentloop_checkpoint(
    self,
    checkpoint: AgentLoopCheckpoint,
) -> None:
    """Save AgentLoop checkpoint to persistence backend.
    
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
agentloop_checkpoint:
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
- Integrate with AgentLoop checkpoint save/load

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

---

## Success Criteria

1. Thread/loop isolation enforced ✓
2. SQLite backend works (per-loop database) ✓
3. PostgreSQL backend works (connection pool) ✓
4. Cross-reference queries work (thread_id → checkpoint_ids) ✓
5. Checkpoint anchors saved correctly ✓
6. Failed branches saved with execution_path ✓
7. Learning insights stored and retrieved ✓
8. Retention policies work (pruning) ✓
9. Metadata.json provides quick access ✓
10. No data duplication ✓

---

## Related Specifications

- RFC-611: AgentLoop Checkpoint Tree Architecture
- RFC-608: AgentLoop Multi-Thread Lifecycle
- RFC-503: Loop-First User Experience
- RFC-411: Event Stream Replay
- RFC-602: SQLite Backend (existing)

---

**End of RFC-613 Draft**