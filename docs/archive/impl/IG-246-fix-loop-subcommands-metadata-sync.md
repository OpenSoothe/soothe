# IG-246: Fix All `soothe loop` Subcommands - Metadata Sync

**Status**: ✅ Completed
**Date**: 2026-04-23
**RFC References**: RFC-608 (Multi-thread spanning), RFC-409 (Persistence backend), RFC-400 (Daemon communication)

---

## Summary

Fix all `soothe loop` subcommands broken for loops created via normal query execution (`soothe "query"`). 

**Root Cause**: Dual storage disconnect between SQLite checkpoint database and filesystem metadata.

**Impact**:
- Loops created via normal queries invisible to all `soothe loop` subcommands
- `soothe loop list/show/tree/prune/subscribe/detach/input` all fail to find valid loops
- Only `soothe loop new` works because it creates metadata.json
- Users cannot inspect or manage loops from their normal workflow

---

## Problem Analysis

### Dual Storage Disconnect

**SQLite Backend** (`loop_checkpoints.db`):
- Written by `AgentLoopStateManager` during query execution
- Stores all loop state (checkpoint, goals, threads, health metrics)
- Source of truth for loop execution and recovery

**Filesystem Metadata** (`data/loops/{loop_id}/metadata.json`):
- Only written by `_handle_loop_new` (i.e., `soothe loop new` command)
- Read by ALL `soothe loop` subcommands
- Contains denormalized subset of checkpoint data

**The Disconnect**: Normal query execution (`soothe "query"` → `AgentLoop.run_with_progress()` → `AgentLoopStateManager`) never creates a loop directory or `metadata.json`, making those loops invisible to every subcommand.

---

## Solution Strategy

**Primary Fix**: Make `AgentLoopStateManager` write `metadata.json` at all key lifecycle points.

**SQLite remains source of truth**; `metadata.json` is a denormalized cache for CLI convenience.

**Self-Healing**: Add fallback in handlers to reconstruct metadata from SQLite for existing/orphaned loops.

---

## Implementation Plan

### 1. Add `_sync_metadata_to_disk()` to AgentLoopStateManager

**File**: `packages/soothe/src/soothe/cognition/agent_loop/state_manager.py`

Add method that derives metadata.json from `self._checkpoint` and writes to loop directory:

```python
def _sync_metadata_to_disk(self) -> None:
    """Sync checkpoint metadata to filesystem (denormalized cache for CLI).
    
    SQLite remains source of truth; metadata.json is for convenience.
    Called automatically from _save_checkpoint_to_db().
    """
    if self._checkpoint is None:
        return
    
    metadata = {
        "loop_id": self._checkpoint.loop_id,
        "status": self._checkpoint.status,
        "thread_ids": self._checkpoint.thread_ids,
        "current_thread_id": self._checkpoint.current_thread_id,
        "total_goals_completed": self._checkpoint.total_goals_completed,
        "total_thread_switches": self._checkpoint.total_thread_switches,
        "total_duration_ms": self._checkpoint.total_duration_ms,
        "total_tokens_used": self._checkpoint.total_tokens_used,
        "schema_version": self._checkpoint.schema_version,
        "created_at": self._checkpoint.created_at.isoformat(),
        "updated_at": self._checkpoint.updated_at.isoformat(),
    }
    
    self.run_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = self.run_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2))
    logger.debug("Synced metadata to disk: %s", metadata_path)
```

**Integration**: Call `self._sync_metadata_to_disk()` at end of `_save_checkpoint_to_db()` to cover all lifecycle points:
- Initialize (`initialize()`)
- Save checkpoint (`save_checkpoint()`)
- Goal lifecycle (`finalize_goal()`)
- Loop lifecycle (`finalize_loop()`)
- Thread switches (`record_iteration()`, `execute_thread_switch()`)

---

### 2. Add `_ensure_loop_metadata()` Helper to MessageRouter

**File**: `packages/soothe/src/soothe/daemon/message_router.py`

Add self-healing helper to reconstruct metadata from SQLite if missing:

```python
async def _ensure_loop_metadata(self, loop_id: str) -> Path | None:
    """Ensure loop dir + metadata.json exist. Reconstruct from SQLite if needed.
    
    Self-healing for:
    - Pre-existing loops (created before this fix)
    - Edge cases where metadata.json was deleted
    
    Args:
        loop_id: Loop identifier
        
    Returns:
        loop_dir Path if loop exists (in filesystem or SQLite), None if not found
    """
    loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)
    metadata_file = loop_dir / "metadata.json"
    
    # Case 1: metadata.json exists → use it
    if metadata_file.exists():
        return loop_dir
    
    # Case 2: metadata.json missing → reconstruct from SQLite
    try:
        db_path = PersistenceDirectoryManager.get_loop_checkpoint_path()
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM agentloop_loops WHERE loop_id = ?",
                (loop_id,)
            )
            row = await cursor.fetchone()
            
            if row is None:
                # Loop doesn't exist in SQLite → truly not found
                return None
            
            # Reconstruct metadata from checkpoint
            metadata = {
                "loop_id": row["loop_id"],
                "status": row["status"],
                "thread_ids": json.loads(row["thread_ids"]),
                "current_thread_id": row["current_thread_id"],
                "total_goals_completed": row["total_goals_completed"],
                "total_thread_switches": row["total_thread_switches"],
                "total_duration_ms": row["total_duration_ms"],
                "total_tokens_used": row["total_tokens_used"],
                "schema_version": row["schema_version"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            
            # Write metadata.json for future use
            loop_dir.mkdir(parents=True, exist_ok=True)
            metadata_file.write_text(json.dumps(metadata, indent=2))
            logger.info("Reconstructed metadata.json for loop %s from SQLite", loop_id)
            
            return loop_dir
            
    except Exception as e:
        logger.error("Failed to reconstruct metadata for loop %s: %s", loop_id, e)
        return None
```

---

### 3. Update All `_handle_loop_*` Methods

**File**: `packages/soothe/src/soothe/daemon/message_router.py`

Replace direct `loop_dir.exists()` checks with `_ensure_loop_metadata()` in:

#### `_handle_loop_get` (~line 1135)
```python
# Before:
loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)
if not loop_dir.exists():
    await d._send_client_message(...)
    return

# After:
loop_dir = await self._ensure_loop_metadata(loop_id)
if loop_dir is None:
    await d._send_client_message(
        client_id,
        {
            "type": "error",
            "code": "LOOP_NOT_FOUND",
            "message": f"Loop {loop_id} not found",
            "request_id": request_id,
        },
    )
    return
```

Apply same pattern to:
- `_handle_loop_tree` (~line 1240)
- `_handle_loop_prune` (~line 1347)
- `_handle_loop_subscribe` (~line 1515)
- `_handle_loop_detach` (~line 1576)
- `_handle_loop_input` (~line 1712)

---

### 4. Fix `_handle_loop_list` with SQLite Fallback

**File**: `packages/soothe/src/soothe/daemon/message_router.py`

Current implementation only scans filesystem directories. Add SQLite fallback:

```python
# 1. Scan filesystem directories (existing logic)
filesystem_loops = set()
for entry in loop_base_dir.iterdir():
    if entry.is_dir() and entry.name != "loop_checkpoints.db":
        filesystem_loops.add(entry.name)

# 2. Query SQLite for loops missing from filesystem
sqlite_loops = set()
db_path = PersistenceDirectoryManager.get_loop_checkpoint_path()
async with aiosqlite.connect(db_path) as db:
    cursor = await db.execute("SELECT loop_id FROM agentloop_loops")
    rows = await cursor.fetchall()
    sqlite_loops = {row[0] for row in rows}

# 3. Find orphaned loops (in SQLite but not in filesystem)
orphaned_loops = sqlite_loops - filesystem_loops

# 4. Self-heal: reconstruct metadata.json for orphaned loops
for loop_id in orphaned_loops:
    await self._ensure_loop_metadata(loop_id)

# 5. Combine and return all loops
all_loops = filesystem_loops | orphaned_loops
```

---

### 5. Fix `_handle_loop_delete` to Clean SQLite

**File**: `packages/soothe/src/soothe/daemon/message_router.py`

Current implementation only deletes filesystem directory. Add SQLite cleanup:

```python
# Delete filesystem directory
loop_dir = await self._ensure_loop_metadata(loop_id)
if loop_dir is None:
    # Already deleted or never existed
    return
    
import shutil
shutil.rmtree(loop_dir)

# Delete from SQLite (all 4 tables)
db_path = PersistenceDirectoryManager.get_loop_checkpoint_path()
async with aiosqlite.connect(db_path) as db:
    await db.execute("DELETE FROM agentloop_loops WHERE loop_id = ?", (loop_id,))
    await db.execute("DELETE FROM checkpoint_anchors WHERE loop_id = ?", (loop_id,))
    await db.execute("DELETE FROM failed_branches WHERE loop_id = ?", (loop_id,))
    await db.execute("DELETE FROM goal_records WHERE loop_id = ?", (loop_id,))
    await db.commit()
    
logger.info("Deleted loop %s from filesystem and SQLite", loop_id)
```

---

### 6. Fix `AgentLoop.run_with_progress()` Parameter

**File**: `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py`

Add `loop_id` parameter (currently missing, causing semantic confusion):

```python
async def run_with_progress(
    self,
    thread_id: str,
    goal: str,
    max_iterations: int = 10,
    loop_id: str | None = None,  # ← NEW: explicit loop_id parameter
    **kwargs,
) -> AgentLoopCheckpoint:
    """Execute goal with progress tracking (RFC-608: multi-thread spanning).
    
    Args:
        thread_id: Thread identifier for execution
        goal: Goal to execute
        max_iterations: Maximum iterations per goal
        loop_id: Optional loop_id (None → auto-generate UUID)
        **kwargs: Additional execution parameters
        
    Returns:
        Final checkpoint after goal completion
    """
    # Initialize state manager with loop_id
    state_manager = AgentLoopStateManager(loop_id=loop_id)
    await state_manager.initialize(thread_id=thread_id, max_iterations=max_iterations)
    ...
```

**File**: `packages/soothe/src/soothe/core/runner/_runner_agentic.py`

No propagation needed yet — `AgentLoopStateManager(loop_id=None)` auto-generates UUID (existing behavior).

---

## Verification Plan

### 1. Run Full Verification Suite
```bash
./scripts/verify_finally.sh
```
- Format check
- Linting (zero errors)
- Unit tests (900+ tests)

### 2. Manual Integration Testing

```bash
# Start daemon
soothed start

# Test normal query execution (creates loop)
soothe --no-tui "test query"
# Expected: completes successfully

# Verify loop appears in list
soothe loop list
# Expected: shows the loop created by query

# Verify all subcommands work
soothe loop show <loop_id>
soothe loop tree <loop_id>
soothe loop input <loop_id> "follow-up query"
soothe loop subscribe <loop_id>
soothe loop detach <loop_id>

# Verify delete cleans both storage
soothe loop delete <loop_id> --force
# Expected: removes filesystem dir + SQLite data

# Test explicit loop creation still works
soothe loop new "test goal"
# Expected: creates loop with metadata.json

# Test self-healing
rm data/loops/<loop_id>/metadata.json
soothe loop list
# Expected: reconstructs metadata.json and shows loop
```

### 3. Edge Case Testing

- Orphaned loops from IG-053 (with index=-1 bug): should self-heal
- Deleted metadata.json: should reconstruct
- Concurrent loop creation: no race conditions
- Large number of loops: list performance

---

## Risk Assessment

**Low Risk**: This is primarily a synchronization fix, not a architectural change.

**SQLite Remains Source of Truth**: metadata.json is denormalized cache, not authoritative.

**Self-Healing**: Automatic recovery for pre-existing loops and edge cases.

**No Breaking Changes**: Backwards compatible with existing `soothe loop new` workflow.

---

## Related Work

- **IG-053**: Fixed checkpoint index calculation bugs (completed 2026-04-23)
- **IG-245**: Refactored persistence architecture (completed)
- **RFC-608**: Multi-thread spanning specification
- **RFC-409**: Unified persistence backend specification

---

## Success Criteria

✅ All `soothe loop` subcommands work for loops from normal queries
✅ `soothe loop list` shows all loops (filesystem + SQLite)
✅ Self-healing works for orphaned loops
✅ Delete removes both filesystem and SQLite data
✅ No performance degradation in loop operations
✅ All tests pass (unit + integration)