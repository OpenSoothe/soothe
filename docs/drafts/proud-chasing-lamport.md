# Fix All `soothe loop` Subcommands

## Context

All `soothe loop` subcommands are broken for loops created via normal query execution (`soothe "query"`). The root cause is a **dual storage disconnect**:

- **SQLite** (`loop_checkpoints.db`): Written by `AgentLoopStateManager` during query execution — stores all loop state
- **Filesystem** (`data/loops/{loop_id}/metadata.json`): Only written by `_handle_loop_new` (i.e., `soothe loop new`) — read by ALL `soothe loop` subcommands

Normal query execution never creates a loop directory or `metadata.json`, making those loops invisible to every subcommand. The fix: make `AgentLoopStateManager` also write `metadata.json` at key lifecycle points (SQLite remains source of truth; metadata.json is a denormalized cache). Add self-healing in handlers to reconstruct metadata from SQLite for existing/orphaned loops.

## Changes

### 1. Add `_sync_metadata_to_disk()` to `AgentLoopStateManager`

**File**: `packages/soothe/src/soothe/cognition/agent_loop/state_manager.py`

Add a method that derives metadata.json from `self._checkpoint` and writes it to the loop directory. Called automatically from `_save_checkpoint_to_db()` so it covers all lifecycle points (initialize, save, finalize_goal, finalize_loop, record_iteration, execute_thread_switch).

```python
def _sync_metadata_to_disk(self) -> None:
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
    (self.run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
```

Call `self._sync_metadata_to_disk()` at the end of `_save_checkpoint_to_db()`.

### 2. Add `_ensure_loop_metadata()` helper to `MessageRouter`

**File**: `packages/soothe/src/soothe/daemon/message_router.py`

Add a helper that reconstructs metadata.json from SQLite if the loop directory/metadata is missing. This provides self-healing for pre-existing loops and edge cases.

```python
async def _ensure_loop_metadata(self, loop_id: str) -> Path | None:
    """Ensure loop dir + metadata.json exist. Reconstruct from SQLite if needed."""
```

Returns the loop_dir Path if the loop exists (in filesystem or SQLite), None otherwise.

### 3. Update all `_handle_loop_*` methods to use `_ensure_loop_metadata()`

**File**: `packages/soothe/src/soothe/daemon/message_router.py`

Replace `loop_dir.exists()` checks with `loop_dir = await self._ensure_loop_metadata(loop_id); if loop_dir is None:` in:

- `_handle_loop_get` (line ~1135)
- `_handle_loop_tree` (line ~1240)
- `_handle_loop_prune` (line ~1347)
- `_handle_loop_subscribe` (line ~1515)
- `_handle_loop_detach` (line ~1576)
- `_handle_loop_input` (line ~1712)

### 4. Fix `_handle_loop_list` with SQLite fallback

**File**: `packages/soothe/src/soothe/daemon/message_router.py`

After scanning filesystem directories, query SQLite for loops missing from the filesystem. Add those to the list and write metadata.json for self-healing.

### 5. Fix `_handle_loop_delete` to also clean SQLite

**File**: `packages/soothe/src/soothe/daemon/message_router.py`

After `shutil.rmtree(loop_dir)`, also delete from all 4 SQLite tables (`agentloop_loops`, `checkpoint_anchors`, `failed_branches`, `goal_records`).

### 6. Add `loop_id` parameter to `AgentLoop.run_with_progress()`

**File**: `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py`

Add `loop_id: str | None = None` parameter. Pass it to `AgentLoopStateManager(loop_id=loop_id, ...)` instead of passing `thread_id` as the first positional arg (which was semantically wrong).

**File**: `packages/soothe/src/soothe/core/runner/_runner_agentic.py`

No `loop_id` propagation needed for now — `AgentLoopStateManager(loop_id=None)` auto-generates a UUID, which is the existing behavior.

## Verification

1. Run `./scripts/verify_finally.sh` (format, lint, tests)
2. Start daemon: `soothe daemon start`
3. Run a query: `soothe --no-tui "test query"` — verify it completes
4. List loops: `soothe loop list` — should now show the loop
5. Show loop: `soothe loop show <loop_id>` — should display details
6. Tree: `soothe loop tree <loop_id>` — should render
7. Delete: `soothe loop delete <loop_id> --force` — should remove both dir and SQLite data
8. Test `soothe loop new` still works
9. Test self-healing: remove a loop's metadata.json, run `soothe loop list` — should reconstruct and show
