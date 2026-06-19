# IG-500: Preserve Loop History on /clear and Create Fresh Loop

**IG**: 500
**Title**: Preserve Loop History on /clear and Create Fresh Loop
**Status**: Draft
**Kind**: Implementation Guide
**Created**: 2026-06-19
**Dependencies**: RFC-216 (Multi-Thread Lifecycle), RFC-454 (Slash Commands), RFC-215 (Persistence)
**Related**: RFC-207 (Thread Context Lifecycle), IG-055 (Backend Selection)

---

## Problem Statement

### Current Behavior

The `/clear` command (RFC-454) is implemented in `packages/soothe-daemon/src/soothe_daemon/server/commands.py` with a TODO placeholder:

```python
async def _cmd_clear(self, checkpoint_thread_id: str | None, params: dict, *, loop_id: str | None = None):
    """Clear conversation history for the bound checkpoint."""
    # TODO: Implement clear_thread in runner
    # await self._runner.clear_thread(checkpoint_thread_id)
    
    await self._broadcast({"type": "clear", "loop_id": lid})
    return {"cleared": True}
```

Current behavior:
- Broadcasts a "clear" event to loop subscribers
- Does NOT archive the loop checkpoint
- Does NOT preserve goal_history
- Does NOT create a new loop

### Expected Behavior

When `/clear` is invoked:
1. **Archive old loop**: Persist checkpoint to archival storage (preserve goal_history, metrics)
2. **Create new loop**: Initialize fresh StrangeLoop with new loop_id
3. **Preserve continuity**: Allow knowledge transfer from archived loop (via /recall)
4. **Update bindings**: Rebind thread to new loop_id

---

## Solution Architecture

### Core Principle: Loop Archive + Thread Rebind

The solution follows RFC-216's thread switching pattern but with explicit archival:

```
/clear triggered
  ├─ 1. Archive current loop checkpoint
  │    └─ SOOTHE_HOME/data/archived_loops/{loop_id}/checkpoint_{timestamp}.json
  ├─ 2. Create new loop (new loop_id, fresh thread_id)
  │    └ StrangeLoopCheckpoint.initialize(new_thread_id)
  ├─ 3. Update daemon thread registry
  │    └ Unbind old loop_id → Bind new loop_id
  └─ 4. Broadcast clear event with archival metadata
       └─ {"type": "clear", "loop_id": new_loop_id, "archived_loop_id": old_loop_id}
```

### Key Distinctions from Thread Switch

| Aspect | Thread Switch (RFC-216) | Clear Archive (This IG) |
|--------|------------------------|------------------------|
| Trigger | Health threshold, relevance | Explicit user command |
| Loop continuity | Same loop_id (thread_ids grows) | New loop_id (fresh start) |
| Thread continuity | Same loop, new thread | New loop, new thread |
| History access | goal_history remains active | Archived, via /recall only |
| Knowledge transfer | Auto /recall on thread switch | Optional /recall from archive |

---

## Implementation Plan

### Phase 1: Persistence Layer — Archive Backend

**Goal**: Add archive storage for loop checkpoints.

**Files**:
- `packages/soothe/src/soothe/foundation/loop/state/persistence/archive_backend.py` (NEW)
- `packages/soothe/src/soothe/foundation/loop/state/persistence/base_backend.py` (MODIFY)

**Archive Backend Design**:

```python
class ArchiveBackend:
    """Archive storage for finalized loops.
    
    Layout:
        SOOTHE_HOME/data/archived_loops/
          {loop_id}/
            checkpoint_{timestamp}.json
            metadata.json  # Loop summary for /recall queries
    """
    
    async def archive_loop(
        self,
        checkpoint: StrangeLoopCheckpoint,
        *,
        reason: Literal["user_clear", "finalized", "expired"],
    ) -> str:
        """Archive loop checkpoint to disk.
        
        Args:
            checkpoint: Complete loop state to archive
            reason: Archival trigger reason
            
        Returns:
            Archive path (relative to SOOTHE_HOME)
        """
        
    async def list_archived_loops(
        self,
        *,
        limit: int = 50,
        after: datetime | None = None,
    ) -> list[ArchiveMetadata]:
        """List archived loops for /recall queries."""
        
    async def get_archive_checkpoint(
        self,
        loop_id: str,
        timestamp: datetime | None = None,
    ) -> StrangeLoopCheckpoint | None:
        """Load archived checkpoint for knowledge transfer."""
```

**ArchiveMetadata Model**:

```python
class ArchiveMetadata(BaseModel):
    """Lightweight archive index entry."""
    
    loop_id: str
    archived_at: datetime
    reason: Literal["user_clear", "finalized", "expired"]
    
    # Summary for /recall search
    goal_count: int
    goals_completed: int
    total_tokens_used: int
    total_duration_ms: int
    
    # Goal summaries for semantic search
    goal_summaries: list[GoalSummary]  # [{goal_id, goal_text, final_report_preview}]
```

---

### Phase 2: State Manager — Archive + Initialize

**Goal**: Add archive and reinitialize methods to StrangeLoopStateManager.

**Files**:
- `packages/soothe/src/soothe/foundation/loop/state/sloop_manager.py` (MODIFY)

**New Methods**:

```python
class StrangeLoopStateManager:
    
    async def archive_and_finalize(
        self,
        *,
        reason: Literal["user_clear", "finalized", "expired"] = "user_clear",
    ) -> ArchiveMetadata:
        """Archive current loop checkpoint and mark as finalized.
        
        RFC-216 compliance: Saves checkpoint to archive storage.
        
        Args:
            reason: Archival trigger
            
        Returns:
            Archive metadata for knowledge transfer
        """
        if self._checkpoint is None:
            raise ValueError("No active checkpoint to archive")
            
        # Mark as finalized
        self._checkpoint.status = "finalized"
        self._checkpoint.updated_at = datetime.now(UTC)
        
        # Archive via backend
        archive_backend = ArchiveBackend()
        archive_path = await archive_backend.archive_loop(
            self._checkpoint,
            reason=reason,
        )
        
        # Generate metadata
        metadata = ArchiveMetadata(
            loop_id=self.loop_id,
            archived_at=datetime.now(UTC),
            reason=reason,
            goal_count=len(self._checkpoint.goal_history),
            goals_completed=sum(
                1 for g in self._checkpoint.goal_history
                if g.status == "completed"
            ),
            total_tokens_used=self._checkpoint.total_tokens_used,
            total_duration_ms=self._checkpoint.total_duration_ms,
            goal_summaries=[
                GoalSummary(
                    goal_id=g.goal_id,
                    goal_text=g.goal_text[:200],
                    final_report_preview=g.goal_completion[:500] if g.goal_completion else "",
                )
                for g in self._checkpoint.goal_history
            ],
        )
        
        # Persist metadata index
        await archive_backend.save_metadata(metadata)
        
        logger.info(
            "Archived loop %s: goals=%d completed=%d reason=%s",
            self.loop_id,
            metadata.goal_count,
            metadata.goals_completed,
            reason,
        )
        
        return metadata
    
    async def reinitialize_for_clear(
        self,
        old_thread_id: str,
    ) -> tuple[str, StrangeLoopCheckpoint]:
        """Create fresh loop after /clear.
        
        Returns:
            (new_loop_id, new_checkpoint)
        """
        # Generate new loop_id
        new_loop_id = str(uuid.uuid4())
        
        # Create fresh checkpoint
        new_checkpoint = StrangeLoopCheckpoint(
            loop_id=new_loop_id,
            thread_ids=[old_thread_id],  # Reuse thread for immediate continuation
            current_thread_id=old_thread_id,
            status="idle",
            goal_history=[],  # Empty
            current_goal_index=-1,
            working_memory_state=WorkingMemoryState(entries=[], spill_files=[]),
            thread_health_metrics=ThreadHealthMetrics(
                thread_id=old_thread_id,
                last_updated=datetime.now(UTC),
            ),
            total_goals_completed=0,
            total_thread_switches=0,
            total_duration_ms=0,
            total_tokens_used=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            schema_version="5.0",
            execution_checkpoint={...},
        )
        
        # Update self
        self.loop_id = new_loop_id
        self._checkpoint = new_checkpoint
        
        # Persist new checkpoint
        await self._save_checkpoint_to_db(new_checkpoint)
        
        logger.info(
            "Reinitialized loop after clear: new_loop_id=%s thread=%s",
            new_loop_id,
            old_thread_id,
        )
        
        return new_loop_id, new_checkpoint
```

---

### Phase 3: Daemon Command Handler — Full Implementation

**Goal**: Implement complete `/clear` logic in daemon.

**Files**:
- `packages/soothe-daemon/src/soothe_daemon/server/commands.py` (MODIFY)
- `packages/soothe-daemon/src/soothe_daemon/runtime/loop_dispatcher.py` (MODIFY)

**`_cmd_clear` Implementation**:

```python
async def _cmd_clear(
    self,
    checkpoint_thread_id: str | None,
    params: dict,
    *,
    loop_id: str | None = None,
) -> dict[str, Any]:
    """Clear conversation history, archive loop, create fresh loop.
    
    Process:
    1. Archive current loop checkpoint
    2. Create new loop with fresh state
    3. Update thread registry bindings
    4. Broadcast clear event with archival metadata
    """
    if not checkpoint_thread_id:
        raise ValueError("Active loop required")
    
    old_loop_id = str(loop_id or "").strip()
    if not old_loop_id:
        raise ValueError("loop_id required for clear operation")
    
    # Get state manager from runner
    if self._runner is None or self._runner.state_manager is None:
        raise ValueError("Runner not initialized")
    
    state_manager = self._runner.state_manager
    
    # 1. Archive old loop
    archive_metadata = await state_manager.archive_and_finalize(
        reason="user_clear",
    )
    
    # 2. Create new loop
    new_loop_id, new_checkpoint = await state_manager.reinitialize_for_clear(
        old_thread_id=checkpoint_thread_id,
    )
    
    # 3. Update thread registry
    self._thread_registry.unbind_loop(checkpoint_thread_id, old_loop_id)
    self._thread_registry.bind_loop(checkpoint_thread_id, new_loop_id)
    
    # 4. Clear LangGraph thread state (reset checkpoint)
    # NOTE: This clears message history in LangGraph's persistence
    await self._runner.clear_thread(checkpoint_thread_id)
    
    # 5. Broadcast clear event with metadata
    await self._broadcast({
        "type": "clear",
        "loop_id": new_loop_id,
        "archived_loop_id": old_loop_id,
        "archive_metadata": {
            "goal_count": archive_metadata.goal_count,
            "goals_completed": archive_metadata.goals_completed,
            "archived_at": archive_metadata.archived_at.isoformat(),
        },
    })
    
    return {
        "cleared": True,
        "new_loop_id": new_loop_id,
        "archived_loop_id": old_loop_id,
        "goals_preserved": archive_metadata.goal_count,
    }
```

**`clear_thread` in Runner** (NEW method):

```python
# In packages/soothe/src/soothe/runner/__init__.py

async def clear_thread(self, thread_id: str) -> None:
    """Clear LangGraph thread checkpoint state.
    
    This resets message history without deleting the thread.
    LangGraph thread_id remains usable for next execution.
    """
    # Use checkpointer's clear/delete method
    if self._checkpointer and hasattr(self._checkpointer, "clear"):
        await self._checkpointer.clear(thread_id)
    else:
        logger.warning("Checkpointer does not support clear operation")
```

---

### Phase 4: Knowledge Transfer from Archived Loops

**Goal**: Enable /recall to query archived loops.

**Files**:
- `packages/soothe/src/soothe/foundation/loop/state/persistence/archive_backend.py` (extend)
- `packages/soothe/src/soothe/protocols/memory/recall.py` (MODIFY - optional)

**Archive Search Method**:

```python
class ArchiveBackend:
    
    async def search_archived_goals(
        self,
        query: str,
        *,
        limit: int = 10,
        min_similarity: float = 0.5,
    ) -> list[ArchivedGoalMatch]:
        """Semantic search across archived loops.
        
        Used for knowledge transfer after /clear.
        """
        # Load metadata index
        all_metadata = await self.list_archived_loops(limit=1000)
        
        # Simple text match (can be upgraded to vector search later)
        matches = []
        for meta in all_metadata:
            for summary in meta.goal_summaries:
                if self._text_match(query, summary.goal_text, min_similarity):
                    matches.append(ArchivedGoalMatch(
                        loop_id=meta.loop_id,
                        goal_id=summary.goal_id,
                        goal_text=summary.goal_text,
                        final_report_preview=summary.final_report_preview,
                        archived_at=meta.archived_at,
                        similarity=self._compute_similarity(query, summary.goal_text),
                    ))
        
        # Sort by similarity, return top-K
        matches.sort(key=lambda m: m.similarity, reverse=True)
        return matches[:limit]
```

**Integration with /recall** (Optional Enhancement):

Add archived loop search to memory recall protocol:

```python
# In memory recall protocol
async def recall(
    self,
    query: str,
    *,
    include_archived: bool = False,
    limit: int = 10,
) -> list[RecallResult]:
    """Recall knowledge from active and archived loops."""
    results = []
    
    # Active loop context (existing)
    results.extend(await self._recall_active_context(query, limit=limit))
    
    # Archived loops (new)
    if include_archived:
        archive_backend = ArchiveBackend()
        archived = await archive_backend.search_archived_goals(query, limit=limit)
        results.extend([
            RecallResult(
                source="archived_loop",
                loop_id=m.loop_id,
                content=m.final_report_preview,
                metadata={"goal_id": m.goal_id, "archived_at": m.archived_at},
            )
            for m in archived
        ])
    
    return results
```

---

### Phase 5: Thread Registry Updates

**Goal**: Add unbind/bind methods for loop reassignment.

**Files**:
- `packages/soothe-daemon/src/soothe_daemon/runtime/thread_registry.py` (NEW or MODIFY existing)

**Registry Interface**:

```python
class ThreadRegistry:
    """Track thread → loop bindings."""
    
    def bind_loop(self, thread_id: str, loop_id: str) -> None:
        """Bind thread to loop (create or update mapping)."""
        
    def unbind_loop(self, thread_id: str, loop_id: str) -> None:
        """Remove thread → loop binding."""
        
    def get_thread_loop(self, thread_id: str) -> str | None:
        """Get loop_id for thread."""
        
    def get_loop_threads(self, loop_id: str) -> list[str]:
        """Get all threads bound to loop."""
```

---

### Phase 6: CLI/TUI Integration

**Goal**: Display archival metadata in UI.

**Files**:
- `packages/soothe-cli/src/soothe_cli/tui/widgets/message_store.py` (MODIFY)
- `apps/soothe-desktop/src/renderer/features/composer/Composer.tsx` (MODIFY - optional)

**Clear Event Rendering**:

```python
# In message_store or event processor
def handle_clear_event(event: dict) -> None:
    """Handle clear event with archival metadata."""
    new_loop_id = event.get("loop_id")
    archived_loop_id = event.get("archived_loop_id")
    metadata = event.get("archive_metadata", {})
    
    # Display clear notification
    self._console.print(
        f"[dim]Conversation cleared. {metadata.get('goals_preserved', 0)} goals "
        f"archived to {archived_loop_id[:8]}...[/dim]"
    )
    
    # Reset message display
    self._messages.clear()
    
    # Update loop binding
    self._current_loop_id = new_loop_id
```

---

## Filesystem Layout

```
SOOTHE_HOME/
  data/
    archived_loops/
      {loop_id}/
        checkpoint_{timestamp}.json   # Full checkpoint
        metadata.json                  # Summary index
    loop_checkpoints.db                # SQLite (active loops)
    threads/
      {thread_id}/
        working_memory/                # Working memory spill
```

---

## Configuration

Add to `config/config.template.yml`:

```yaml
persistence:
  archive_enabled: true
  archive_retention_days: 90  # Days to keep archived loops
  archive_max_count: 1000     # Maximum archived loops

agentic:
  clear_preserves_history: true  # Enable archival on /clear
  clear_recall_enabled: true     # Allow /recall from archives
```

---

## Test Cases

### Unit Tests

**Location**: `packages/soothe/tests/unit/foundation/loop/state/`

1. `test_archive_backend_archive_loop.py`
   - Archive checkpoint to disk
   - Verify JSON serialization
   - Verify metadata generation

2. `test_archive_backend_search.py`
   - Search archived goals
   - Verify similarity ranking

3. `test_sloop_manager_archive_finalize.py`
   - Archive and finalize
   - Verify status transition

4. `test_sloop_manager_reinitialize.py`
   - Create fresh loop after clear
   - Verify new loop_id

### Integration Tests

**Location**: `packages/soothe-daemon/tests/integration/`

1. `test_clear_command_flow.py`
   - Execute /clear via daemon RPC
   - Verify archival + new loop creation
   - Verify thread registry update

2. `test_clear_recall_integration.py`
   - Clear loop, then /recall from archive
   - Verify knowledge transfer

---

## Backward Compatibility

- **Existing `/clear` callers**: Returns same `{"cleared": True}` + additional metadata
- **Loop checkpoints**: No schema changes (archive uses same schema)
- **Thread continuity**: Thread_id reused for immediate continuation

---

## Open Questions

1. **Thread reuse vs new thread**: Should `/clear` reuse same thread_id or create fresh thread?
   - **Proposal**: Reuse thread_id for immediate continuation (simpler UX)
   - Alternative: Create fresh thread_id (cleaner isolation)

2. **Archive retention**: Auto-delete archives after N days?
   - **Proposal**: Configurable retention (default 90 days)

3. **/recall from archive**: Should this be automatic or explicit?
   - **Proposal**: Explicit `/recall --archived` flag
   - Alternative: Include in regular /recall (may add noise)

---

## Success Criteria

1. `/clear` archives loop checkpoint with goal_history
2. New loop created with fresh state
3. Thread registry updated to new loop_id
4. Archived goals searchable via /recall
5. UI displays archival metadata
6. Tests pass for archive flow

---

## Estimated Effort

| Phase | Effort |
|-------|--------|
| Phase 1: Archive Backend | 2 hours |
| Phase 2: State Manager | 1.5 hours |
| Phase 3: Daemon Handler | 2 hours |
| Phase 4: Knowledge Transfer | 1.5 hours |
| Phase 5: Thread Registry | 1 hour |
| Phase 6: CLI Integration | 1 hour |
| Tests | 3 hours |
| **Total** | **11 hours** |

---

## References

- RFC-216: StrangeLoop Multi-Thread Lifecycle
- RFC-454: Slash Command Architecture
- RFC-215: Persistence Backend
- RFC-207: Thread Context Lifecycle
- IG-055: Backend Selection Pattern