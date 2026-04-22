# AgentLoop Persistence Backend Implementation

> Implementation guide for SQLite/PostgreSQL persistence backend with thread/loop isolation (RFC-409).
>
> **Crate/Module**: `packages/soothe/src/soothe/core/persistence/`, `packages/soothe/src/soothe/cognition/agent_loop/`
> **Source**: Derived from RFC-409 (AgentLoop Persistence Backend), RFC-611 (Checkpoint Tree Architecture)
> **Related RFCs**: RFC-608, RFC-503, RFC-411
> **Language**: Python 3.11+
> **Framework**: aiosqlite, asyncpg, Pydantic

---

## 1. Overview

This implementation guide specifies the creation of AgentLoop persistence backend with **thread/loop isolation** and dual backend support (SQLite/PostgreSQL). The implementation enforces architectural separation: thread data (CoreAgent Layer 1) and loop data (AgentLoop Layer 2) stored in isolated directory structures with cross-reference linkage.

### 1.1 Purpose

Implement persistence infrastructure for AgentLoop checkpoint trees that enables:
- Thread/loop directory isolation (`data/threads/` vs `data/loops/`)
- SQLite backend (primary) with per-loop database files
- PostgreSQL backend (secondary) with connection pooling
- Checkpoint anchor persistence (iteration synchronization)
- Failed branch persistence (learning history)
- Goal record persistence (execution history)

### 1.2 Scope

**In Scope**:
- Directory structure creation (`$SOOTHE_HOME/data/threads/`, `$SOOTHE_HOME/data/loops/`)
- SQLite schema implementation (per-loop database)
- PostgreSQL schema implementation (shared database)
- Persistence manager API (save/load/query operations)
- AgentLoopCheckpoint v3.1 schema migration
- Integration with AgentLoopStateManager
- Configuration integration

**Out of Scope**:
- CoreAgent checkpoint persistence (managed by LangGraph)
- Event stream replay (RFC-411, Phase 4)
- Loop UX transformation (RFC-503, Phase 3)
- Checkpoint tree visualization (RFC-504, Phase 3)

---

## 2. Directory Structure Implementation

### 2.1 Create Isolated Data Directories

**Location**: `packages/soothe/src/soothe/config/constants.py`

```python
# Add new constants for isolated data directories

THREADS_DATA_DIR = "data/threads"
"""Directory for CoreAgent thread runtime data (Layer 1)."""

LOOPS_DATA_DIR = "data/loops"
"""Directory for AgentLoop checkpoint data (Layer 2)."""
```

**Implementation**: `packages/soothe/src/soothe/core/persistence/directory_manager.py`

```python
from pathlib import Path
from soothe.config.constants import THREADS_DATA_DIR, LOOPS_DATA_DIR, SOOTHE_HOME

class PersistenceDirectoryManager:
    """Manager for isolated persistence directories."""
    
    @staticmethod
    def ensure_directories_exist() -> None:
        """Create isolated data directories if they don't exist."""
        
        threads_dir = Path(SOOTHE_HOME).expanduser() / THREADS_DATA_DIR
        loops_dir = Path(SOOTHE_HOME).expanduser() / LOOPS_DATA_DIR
        
        threads_dir.mkdir(parents=True, exist_ok=True)
        loops_dir.mkdir(parents=True, exist_ok=True)
    
    @staticmethod
    def get_thread_directory(thread_id: str) -> Path:
        """Get CoreAgent thread directory path.
        
        Args:
            thread_id: Thread identifier.
        
        Returns:
            Path to thread's data directory.
        """
        return Path(SOOTHE_HOME).expanduser() / THREADS_DATA_DIR / thread_id
    
    @staticmethod
    def get_loop_directory(loop_id: str) -> Path:
        """Get AgentLoop loop directory path.
        
        Args:
            loop_id: Loop identifier.
        
        Returns:
            Path to loop's data directory.
        """
        return Path(SOOTHE_HOME).expanduser() / LOOPS_DATA_DIR / loop_id
```

---

## 3. SQLite Backend Implementation

### 3.1 Create Database Schema

**Location**: `packages/soothe/src/soothe/core/persistence/sqlite_backend.py`

```python
import aiosqlite
import json
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

class SQLitePersistenceBackend:
    """SQLite backend for AgentLoop checkpoint persistence."""
    
    SCHEMA_VERSION = "3.1"
    
    @staticmethod
    async def initialize_database(db_path: Path) -> None:
        """Initialize SQLite database schema.
        
        Args:
            db_path: Path to SQLite database file.
        """
        async with aiosqlite.connect(db_path) as db:
            # Create agentloop_loops table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS agentloop_loops (
                    loop_id TEXT PRIMARY KEY,
                    thread_ids TEXT NOT NULL,
                    current_thread_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_goals_completed INTEGER DEFAULT 0,
                    total_thread_switches INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    schema_version TEXT DEFAULT '3.1'
                )
            """)
            
            # Create checkpoint_anchors table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS checkpoint_anchors (
                    anchor_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    loop_id TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    thread_id TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    checkpoint_ns TEXT DEFAULT '',
                    anchor_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    iteration_status TEXT,
                    next_action_summary TEXT,
                    tools_executed TEXT,
                    reasoning_decision TEXT,
                    FOREIGN KEY (loop_id) REFERENCES agentloop_loops(loop_id),
                    UNIQUE(loop_id, iteration, anchor_type)
                )
            """)
            
            # Create indexes for checkpoint_anchors
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_anchors_loop_iteration 
                ON checkpoint_anchors(loop_id, iteration)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_anchors_thread 
                ON checkpoint_anchors(thread_id)
            """)
            
            # Create failed_branches table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS failed_branches (
                    branch_id TEXT PRIMARY KEY,
                    loop_id TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    thread_id TEXT NOT NULL,
                    root_checkpoint_id TEXT NOT NULL,
                    failure_checkpoint_id TEXT NOT NULL,
                    failure_reason TEXT NOT NULL,
                    execution_path TEXT NOT NULL,
                    failure_insights TEXT,
                    avoid_patterns TEXT,
                    suggested_adjustments TEXT,
                    created_at TEXT NOT NULL,
                    analyzed_at TEXT,
                    pruned_at TEXT,
                    FOREIGN KEY (loop_id) REFERENCES agentloop_loops(loop_id)
                )
            """)
            
            # Create indexes for failed_branches
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_branches_loop 
                ON failed_branches(loop_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_branches_thread 
                ON failed_branches(thread_id)
            """)
            
            # Create goal_records table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS goal_records (
                    goal_id TEXT PRIMARY KEY,
                    loop_id TEXT NOT NULL,
                    goal_text TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    reason_history TEXT,
                    act_history TEXT,
                    final_report TEXT,
                    evidence_summary TEXT,
                    duration_ms INTEGER DEFAULT 0,
                    tokens_used INTEGER DEFAULT 0,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY (loop_id) REFERENCES agentloop_loops(loop_id)
                )
            """)
            
            # Create indexes for goal_records
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_goals_loop 
                ON goal_records(loop_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_goals_thread 
                ON goal_records(thread_id)
            """)
            
            await db.commit()
```

---

## 4. Persistence Manager API Implementation

### 4.1 Core Persistence Manager

**Location**: `packages/soothe/src/soothe/core/persistence/manager.py`

```python
from typing import Literal, Any
from pathlib import Path
from datetime import datetime, UTC

from soothe.core.persistence.sqlite_backend import SQLitePersistenceBackend
from soothe.core.persistence.directory_manager import PersistenceDirectoryManager

class AgentLoopCheckpointPersistenceManager:
    """Manager for AgentLoop checkpoint persistence."""
    
    def __init__(self, backend: Literal["sqlite", "postgresql"] = "sqlite"):
        """Initialize persistence manager.
        
        Args:
            backend: Database backend type (default: sqlite).
        """
        self.backend = backend
        PersistenceDirectoryManager.ensure_directories_exist()
    
    async def save_checkpoint_anchor(
        self,
        loop_id: str,
        iteration: int,
        thread_id: str,
        checkpoint_id: str,
        anchor_type: str,
        execution_summary: dict[str, Any] | None = None,
    ) -> None:
        """Save iteration checkpoint anchor.
        
        Args:
            loop_id: AgentLoop identifier.
            iteration: Iteration number.
            thread_id: Thread where checkpoint belongs.
            checkpoint_id: CoreAgent checkpoint_id.
            anchor_type: "iteration_start", "iteration_end", "failure_point".
            execution_summary: Optional execution metadata.
        """
        loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)
        db_path = loop_dir / "checkpoint.db"
        
        # Ensure database exists
        await SQLitePersistenceBackend.initialize_database(db_path)
        
        # Insert anchor
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO checkpoint_anchors
                (loop_id, iteration, thread_id, checkpoint_id, checkpoint_ns, 
                 anchor_type, timestamp, iteration_status, next_action_summary,
                 tools_executed, reasoning_decision)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                loop_id,
                iteration,
                thread_id,
                checkpoint_id,
                "",  # checkpoint_ns
                anchor_type,
                datetime.now(UTC).isoformat(),
                execution_summary.get("status") if execution_summary else None,
                execution_summary.get("next_action_summary") if execution_summary else None,
                json.dumps(execution_summary.get("tools_executed", [])) if execution_summary else None,
                execution_summary.get("reasoning_decision") if execution_summary else None,
            ))
            await db.commit()
    
    async def get_checkpoint_anchors_for_range(
        self,
        loop_id: str,
        start_iteration: int,
        end_iteration: int,
    ) -> list[dict[str, Any]]:
        """Get checkpoint anchors for iteration range.
        
        Args:
            loop_id: AgentLoop identifier.
            start_iteration: Start iteration (inclusive).
            end_iteration: End iteration (inclusive).
        
        Returns:
            List of checkpoint anchors.
        """
        loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)
        db_path = loop_dir / "checkpoint.db"
        
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("""
                SELECT iteration, thread_id, checkpoint_id, anchor_type, timestamp,
                       iteration_status, tools_executed, reasoning_decision
                FROM checkpoint_anchors
                WHERE loop_id = ? AND iteration BETWEEN ? AND ?
                ORDER BY iteration, anchor_type
            """, (loop_id, start_iteration, end_iteration)) as cursor:
                rows = await cursor.fetchall()
                
                return [
                    {
                        "iteration": row[0],
                        "thread_id": row[1],
                        "checkpoint_id": row[2],
                        "anchor_type": row[3],
                        "timestamp": row[4],
                        "iteration_status": row[5],
                        "tools_executed": json.loads(row[6]) if row[6] else [],
                        "reasoning_decision": row[7],
                    }
                    for row in rows
                ]
```

---

## 5. AgentLoopCheckpoint v3.1 Schema Migration

### 5.1 Update Checkpoint Schema

**Location**: `packages/soothe/src/soothe/cognition/agent_loop/checkpoint.py`

```python
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime

class CoreAgentCheckpointTreeRef(BaseModel):
    """Reference to CoreAgent checkpoint tree structure."""
    
    main_line_checkpoints: dict[int, str] = Field(default_factory=dict)
    """Mapping: iteration → checkpoint_id on main successful execution line."""
    
    failed_branches: dict[str, FailedBranchRecord] = Field(default_factory=dict)
    """Mapping: branch_id → failed branch execution record."""
    
    current_head_checkpoint_id: str | None = None
    """Latest checkpoint_id on current branch."""


class AgentLoopCheckpoint(BaseModel):
    """Complete AgentLoop state with checkpoint tree reference (v3.1)."""
    
    # Identity (RFC-608)
    loop_id: str
    thread_ids: list[str] = Field(default_factory=list)
    current_thread_id: str
    
    # NEW: Checkpoint tree reference (v3.1)
    checkpoint_tree_ref: CoreAgentCheckpointTreeRef = Field(
        default_factory=CoreAgentCheckpointTreeRef
    )
    """Reference to CoreAgent checkpoint tree with branch management."""
    
    # CoreAgent checkpoint references (v3.0 from IG-238)
    coreagent_checkpoint_refs: dict[str, CoreAgentCheckpointRef] = Field(
        default_factory=dict
    )
    """Mapping: thread_id → CoreAgent checkpoint metadata."""
    
    # Status (RFC-608)
    status: Literal["running", "ready_for_next_goal", "finalized", "cancelled"]
    
    # Goal execution history (RFC-608)
    goal_history: list[GoalExecutionRecord] = Field(default_factory=list)
    current_goal_index: int = -1
    
    # Working memory (RFC-608)
    working_memory_state: WorkingMemoryState = Field(
        default_factory=WorkingMemoryState
    )
    
    # Thread health (RFC-608)
    thread_health_metrics: ThreadHealthMetrics
    
    # RFC-609: Goal context injection
    thread_switch_pending: bool = False
    
    # Loop metrics
    total_goals_completed: int = 0
    total_thread_switches: int = 0
    total_duration_ms: int = 0
    total_tokens_used: int = 0
    
    # Timestamps
    created_at: datetime
    updated_at: datetime
    
    schema_version: str = "3.1"  # v3.1 adds checkpoint_tree_ref
```

---

## 6. Integration with AgentLoopStateManager

### 6.1 Add Persistence Integration

**Location**: `packages/soothe/src/soothe/cognition/agent_loop/state_manager.py`

```python
from soothe.core.persistence.manager import AgentLoopCheckpointPersistenceManager

class AgentLoopStateManager:
    """Manager for AgentLoop state with persistence integration."""
    
    def __init__(self, loop_id: str):
        """Initialize state manager.
        
        Args:
            loop_id: AgentLoop identifier.
        """
        self.loop_id = loop_id
        self.persistence_manager = AgentLoopCheckpointPersistenceManager()
        self.checkpoint_path = PersistenceDirectoryManager.get_loop_directory(loop_id) / "metadata.json"
    
    async def save_checkpoint_anchor(
        self,
        iteration: int,
        thread_id: str,
        checkpoint_id: str,
        anchor_type: str,
    ) -> None:
        """Save checkpoint anchor during iteration execution.
        
        Args:
            iteration: Current iteration number.
            thread_id: Current thread ID.
            checkpoint_id: CoreAgent checkpoint ID.
            anchor_type: Anchor type.
        """
        await self.persistence_manager.save_checkpoint_anchor(
            loop_id=self.loop_id,
            iteration=iteration,
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            anchor_type=anchor_type,
        )
```

---

## 7. Configuration Integration

### 7.1 Add Configuration Options

**Location**: `packages/soothe/src/soothe/config/config.py`

```python
class SootheConfig(BaseSettings):
    # Add persistence backend configuration
    
    agentloop_persistence_backend: Literal["sqlite", "postgresql"] = "sqlite"
    """AgentLoop checkpoint persistence backend type."""
    
    agentloop_persistence_sqlite_db_dir: str = "$SOOTHE_HOME/data/loops"
    """SQLite database directory for AgentLoop checkpoints."""
    
    agentloop_persistence_postgresql_pool_size: int = 10
    """PostgreSQL connection pool size for AgentLoop checkpoints."""
    
    agentloop_persistence_retention_branch_days: int = 30
    """Retention days for failed branches."""
    
    agentloop_persistence_retention_anchor_days: int = 90
    """Retention days for checkpoint anchors."""
```

**Config template**: `packages/soothe/src/soothe/config/config.yml`

```yaml
agentloop_checkpoint:
  persistence_backend: "sqlite"  # "sqlite" or "postgresql"
  
  sqlite:
    db_dir: "$SOOTHE_HOME/data/loops"
    
  postgresql:
    connection_pool_size: 10
    
  retention:
    failed_branch_days: 30
    checkpoint_anchor_days: 90
    goal_record_days: 180
```

---

## 8. Testing Strategy

### 8.1 Unit Tests

**Location**: `tests/unit/core/persistence/test_manager.py`

```python
import pytest
from soothe.core.persistence.manager import AgentLoopCheckpointPersistenceManager

@pytest.mark.asyncio
async def test_save_checkpoint_anchor():
    """Test saving checkpoint anchor."""
    
    manager = AgentLoopCheckpointPersistenceManager()
    
    await manager.save_checkpoint_anchor(
        loop_id="test_loop",
        iteration=0,
        thread_id="test_thread",
        checkpoint_id="checkpoint_abc",
        anchor_type="iteration_start",
    )
    
    anchors = await manager.get_checkpoint_anchors_for_range("test_loop", 0, 0)
    
    assert len(anchors) == 1
    assert anchors[0]["iteration"] == 0
    assert anchors[0]["thread_id"] == "test_thread"
    assert anchors[0]["checkpoint_id"] == "checkpoint_abc"
```

---

## 9. Verification Procedure

```bash
# Run unit tests
make test-unit

# Manual verification
soothe doctor --check persistence

# Verify directory structure
ls -la $SOOTHE_HOME/data/threads/
ls -la $SOOTHE_HOME/data/loops/
```

---

## 10. Critical Files

### 10.1 Files to Create

- `packages/soothe/src/soothe/core/persistence/__init__.py`
- `packages/soothe/src/soothe/core/persistence/directory_manager.py`
- `packages/soothe/src/soothe/core/persistence/sqlite_backend.py`
- `packages/soothe/src/soothe/core/persistence/manager.py`
- `packages/soothe/src/soothe/core/persistence/postgresql_backend.py` (Phase 2)
- `tests/unit/core/persistence/test_manager.py`

### 10.2 Files to Modify

- `packages/soothe/src/soothe/config/constants.py` (add THREADS_DATA_DIR, LOOPS_DATA_DIR)
- `packages/soothe/src/soothe/config/config.py` (add persistence configuration)
- `packages/soothe/src/soothe/config/config.yml` (add agentloop_checkpoint section)
- `packages/soothe/src/soothe/cognition/agent_loop/checkpoint.py` (update schema to v3.1)
- `packages/soothe/src/soothe/cognition/agent_loop/state_manager.py` (add persistence integration)

---

**End of Phase 1 Implementation Guide (IG-239)**