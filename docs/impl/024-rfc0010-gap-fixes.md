# IG-024: RFC-0010 Gap Fixes

**Implements**: RFC-0010 (Gap Remediation)
**Status**: Completed
**Created**: 2026-03-18
**Related**: IG-023

## Overview

This implementation guide addresses gaps identified in the RFC-0010 spec-to-code review:
1. Missing `soothe.checkpoint.saved` stream event emission
2. Thread deletion cleanup verification and implementation

## Gap 1: Stream Event Emission

### Problem

RFC-0010 specifies two stream events for observability:
- `soothe.recovery.resumed` ✅ (already implemented)
- `soothe.checkpoint.saved` ❌ (not emitted)

Currently, checkpoints are saved but no stream event is emitted, preventing external monitoring tools from tracking checkpoint progress.

### Solution

Emit `soothe.checkpoint.saved` event after each successful checkpoint save in `_save_checkpoint()`.

### Changes Required

**File**: `src/soothe/core/runner.py`

**Method**: `_save_checkpoint()`

**Current Code** (approximate location: line 1060-1082):
```python
async def _save_checkpoint(
    self, state: RunnerState, *, user_input: str,
    mode: str = "single_pass", status: str = "in_progress",
) -> None:
    if not self._artifact_store:
        return
    # ... build envelope ...
    try:
        self._artifact_store.save_checkpoint(envelope)
    except Exception:
        logger.debug("Checkpoint save failed", exc_info=True)
```

**Modified Code**:
```python
async def _save_checkpoint(
    self, state: RunnerState, *, user_input: str,
    mode: str = "single_pass", status: str = "in_progress",
) -> AsyncGenerator[StreamChunk, None]:
    """Save progressive checkpoint and emit stream event.

    Yields:
        soothe.checkpoint.saved event on success.
    """
    if not self._artifact_store:
        return

    plan_data = state.plan.model_dump(mode="json") if state.plan else None
    completed = [
        s.id for s in (state.plan.steps if state.plan else [])
        if s.status == "completed"
    ]
    goals_data = self._goal_engine.snapshot() if self._goal_engine else []

    envelope = {
        "version": 1,
        "timestamp": datetime.now(UTC).isoformat(),
        "mode": mode,
        "last_query": user_input,
        "thread_id": state.thread_id,
        "goals": goals_data,
        "active_goal_id": None,
        "plan": plan_data,
        "completed_step_ids": completed,
        "total_iterations": 0,
        "status": status,
    }

    try:
        self._artifact_store.save_checkpoint(envelope)
        yield {
            "type": "soothe.checkpoint.saved",
            "thread_id": state.thread_id,
            "completed_steps": len(completed),
            "completed_goals": len(goals_data),
        }
    except Exception:
        logger.debug("Checkpoint save failed", exc_info=True)
```

**Important**: This changes the method signature from `async def` returning `None` to `AsyncGenerator[StreamChunk, None]`.

### Call Site Updates

All call sites of `_save_checkpoint()` must be updated to iterate over the generator (even if they discard the yielded events).

**Locations**:
1. `_run_step_loop()` - after each step (line ~1228)
2. `_run_step_loop()` - after parallel batch (line ~1275)
3. `_execute_autonomous_goal()` - after each goal (line ~1103)
4. `_run_autonomous()` - at end (line ~838)
5. `_post_stream()` - at end (line ~1869)

**Example Update** (for single checkpoint):
```python
# Before
await self._save_checkpoint(state, user_input=..., mode=..., status=...)

# After
async for _ in self._save_checkpoint(state, user_input=..., mode=..., status=...):
    pass  # Events are emitted but not propagated further
```

**Alternative** (if you want to propagate events):
```python
async for chunk in self._save_checkpoint(state, user_input=..., mode=..., status=...):
    yield chunk  # Propagate to caller's stream
```

### Testing

Add test in `tests/unit_tests/test_durability.py` or `tests/unit_tests/test_runner.py`:

```python
async def test_checkpoint_saved_event_emitted():
    """Verify soothe.checkpoint.saved event is emitted."""
    runner = SootheRunner(config)
    state = RunnerState(thread_id="test-123")

    events = []
    async for chunk in runner._save_checkpoint(state, user_input="test", mode="single_pass"):
        events.append(chunk)

    assert len(events) == 1
    assert events[0]["type"] == "soothe.checkpoint.saved"
    assert events[0]["thread_id"] == "test-123"
    assert "completed_steps" in events[0]
    assert "completed_goals" in events[0]
```

## Gap 2: Thread Deletion Cleanup

### Problem

RFC-0010 specifies that thread deletion should remove the entire `runs/{thread_id}/` directory, but this behavior has not been verified in the implementation.

### Investigation Needed

Search for thread deletion logic in:
1. `src/soothe/cli/commands.py` - `/delete` command
2. `src/soothe/cli/main.py` - thread management commands
3. `src/soothe/cli/daemon.py` - thread cleanup

### Expected Behavior

When a thread is deleted:
1. Remove `$SOOTHE_HOME/runs/{thread_id}/` directory (artifacts, checkpoints, reports)
2. Call `durability.archive_thread(thread_id)` (thread metadata)
3. Optionally: Remove conversation log if not already covered

### Implementation

**If thread deletion exists**:

**File**: Location of `/delete` command handler

**Add**:
```python
import shutil
from soothe.config import SOOTHE_HOME

def handle_thread_deletion(thread_id: str) -> None:
    """Delete thread artifacts and metadata."""
    # Remove runs directory
    runs_dir = Path(SOOTHE_HOME) / "runs" / thread_id
    if runs_dir.exists():
        shutil.rmtree(runs_dir)
        logger.info("Deleted thread artifacts: %s", runs_dir)

    # Archive thread metadata (existing durability call)
    durability.archive_thread(thread_id)
```

**If thread deletion does NOT exist**:

Add a new slash command in `src/soothe/cli/commands.py`:

```python
@register_command("/delete")
async def handle_delete(
    args: str,
    runner: SootheRunner,
    console: Console,
    **kwargs,
) -> bool:
    """Delete the current thread and its artifacts.

    Usage: /delete [thread_id]

    If thread_id is provided, deletes that thread.
    Otherwise, deletes the current thread.
    """
    import shutil
    from soothe.config import SOOTHE_HOME

    thread_id = args.strip() or runner.current_thread_id
    if not thread_id:
        console.print("[red]No thread to delete[/red]")
        return False

    # Confirm deletion
    console.print(f"[yellow]Delete thread {thread_id}?[/yellow] (y/n): ", end="")
    # Note: In actual implementation, need to handle async input

    # Remove runs directory
    runs_dir = Path(SOOTHE_HOME) / "runs" / thread_id
    if runs_dir.exists():
        shutil.rmtree(runs_dir)
        console.print(f"[green]Deleted artifacts: {runs_dir}[/green]")

    # Archive thread metadata
    runner.durability.archive_thread(thread_id)
    console.print(f"[green]Thread {thread_id} deleted[/green]")

    # Clear current thread
    if runner.current_thread_id == thread_id:
        runner.current_thread_id = None

    return False  # Don't exit
```

### Testing

Add test:

```python
def test_thread_deletion_removes_runs_directory(tmp_path):
    """Verify /delete removes runs/{thread_id}/ directory."""
    from soothe.cli.commands import handle_delete
    from soothe.core.runner import SootheRunner

    # Create a thread with artifacts
    thread_id = "test-thread-123"
    runs_dir = tmp_path / "runs" / thread_id
    runs_dir.mkdir(parents=True)
    (runs_dir / "checkpoint.json").write_text('{"status": "completed"}')

    # Delete the thread
    runner = SootheRunner(config)
    runner.current_thread_id = thread_id
    # ... call handle_delete ...

    # Verify runs directory is gone
    assert not runs_dir.exists()
```

## Implementation Order

1. **Phase 1**: Emit `soothe.checkpoint.saved` event
   - Modify `_save_checkpoint()` signature
   - Update all call sites (5 locations)
   - Add test for event emission

2. **Phase 2**: Verify and implement thread deletion
   - Search for existing `/delete` command
   - Add cleanup logic if missing
   - Add test for directory removal

## Verification Checklist

- [ ] `_save_checkpoint()` yields stream events
- [ ] All call sites updated to iterate generator
- [ ] Test: `soothe.checkpoint.saved` event emitted
- [ ] Thread deletion removes `runs/{thread_id}/`
- [ ] Test: directory cleanup verified
- [ ] Manual test: create thread, save checkpoint, delete, verify cleanup

## Files to Modify

| File | Changes |
|------|---------|
| `core/runner.py` | `_save_checkpoint()` yields events, update call sites |
| `cli/commands.py` | Add/verify `/delete` command with runs/ cleanup |
| `tests/unit_tests/test_runner.py` | Add checkpoint event test |
| `tests/unit_tests/test_commands.py` | Add deletion test |

## Backward Compatibility

No breaking changes:
- Stream event emission is additive
- Thread deletion cleanup is enhancement
- Existing functionality preserved
