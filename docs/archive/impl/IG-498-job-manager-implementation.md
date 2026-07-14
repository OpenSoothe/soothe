# IG-498: JobManager Implementation (RFC-228, RFC-626)

> **Status**: Completed
> **RFC**: RFC-228 (Autopilot Job IPC Commands), RFC-626 (Entity Model Consolidation)
> **Created**: 2026-06-16
> **Updated**: 2026-06-16
> **Dependencies**: RFC-222, RFC-624, RFC-625

## Progress

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | ✅ Completed | JobManager class with lifecycle transitions |
| Phase 2 | ✅ Completed | Checkpoint persistence via AsyncPersistStore |
| Phase 3 | ✅ Completed | Unit tests for lifecycle transitions |
| Phase 4 | ✅ Completed | Integration verification and lint compliance |

## Files Created

| Package | File | Description |
|---------|------|-------------|
| soothe | `foundation/core/managers/__init__.py` | Module init exposing JobManager |
| soothe | `foundation/core/managers/job_manager.py` | JobManager class implementation (531 lines) |
| soothe | `tests/unit/foundation/core/managers/__init__.py` | Test module init |
| soothe | `tests/unit/foundation/core/managers/test_job_manager.py` | Unit tests (23 tests, all passing) |

## Files Modified

| Package | File | Changes |
|---------|------|---------|
| soothe | `foundation/core/entities/job.py` | Added `active_goals` field to Job dataclass |

## Goal

Implement JobManager for managing job lifecycle transitions and checkpoint persistence per RFC-228 (Autopilot Job IPC Commands) and RFC-626 (Entity Model Consolidation).

## Scope

| In Scope | Out of Scope |
|----------|--------------|
| Job lifecycle transitions (create, pause, resume, cancel) | Job execution (handled by StrangeLoop) |
| Checkpoint persistence via AsyncPersistStore | Job DAG visualization (handled by AutopilotService) |
| Status queries and IPC response building | WebSocket RPC handlers (already implemented in IG-471) |
| Job-to-GoalNode mapping per RFC-626 | GoalEngine operations (handled by ContextEngine) |

## Design Decisions

### 1. JobManager Architecture

**Decision**: JobManager operates directly on ContextEngine GoalNode entities without intermediate wrapper models.

**Rationale**: RFC-626 §2 eliminates intermediate state containers (Goal, LoopState) and consolidates all entity models under ContextEngine. JobManager follows this pattern by:
- Using ContextEngine APIs directly for goal operations
- Converting GoalNode to Job value object for query responses
- Persisting JobCheckpoint via AsyncPersistStore pattern

### 2. Checkpoint Persistence Strategy

**Decision**: Persist JobCheckpoint (execution metadata only) separate from GoalNode state.

**Rationale**: RFC-626 §4 ExecutionCheckpoint pattern stores execution-only fields (worker_id, token counts, duration) not goal-level state (description, steps, ledger). GoalNode state is recovered from CE persistence on restart. This separation:
- Reduces checkpoint payload size
- Avoids duplicate persistence of goal state
- Enables job-level recovery metrics even if goal DAG is rebuilt

### 3. Lifecycle Transition Validation

**Decision**: Validate state transitions before calling ContextEngine methods.

**Rationale**: ContextEngine goal methods (suspend_goal, reactivate_goal, cancel_goal) may have broader transition rules. JobManager enforces job-specific constraints:
- Cannot pause/resume/cancel terminal state jobs
- Resume only valid from suspended state
- Explicit validation errors with job_id and state context

## Implementation Details

### JobManager Class Structure

```python
class JobManager:
    """Manage job lifecycle transitions and checkpoint persistence."""
    
    def __init__(self, ce: ContextEngine, persist_store: AsyncPersistStore | None = None):
        self._ce = ce
        self._persist_store = persist_store
    
    # Lifecycle Operations
    async def create_job(description, priority, workspace, source_file) -> Job
    async def pause_job(job_id, reason) -> Job | None
    async def resume_job(job_id) -> Job | None
    async def cancel_job(job_id, reason) -> Job | None
    
    # Status Queries
    async def get_job(job_id) -> Job | None
    async def get_job_checkpoint(job_id) -> JobCheckpoint | None
    async def list_jobs(status, limit) -> list[Job]
    async def get_job_status_response(job_id) -> dict | None
    
    # Checkpoint Persistence
    async def _persist_checkpoint(job_id, checkpoint) -> None
    async def restore_checkpoints() -> list[str]
    async def delete_checkpoint(job_id) -> bool
    
    # Helpers
    def _goal_to_job(goal) -> Job
    def _build_checkpoint(job) -> JobCheckpoint
    def _collect_descendant_ids(job_id, all_goals) -> set[str]
```

### Checkpoint Key Schema

```
autopilot:job_checkpoint:{job_id}
```

Follows `DurabilityGoalDispatchContextStore` pattern from RFC-222 with `autopilot:` namespace prefix.

### Status Response Schema

Matches RFC-228 §79 `job_status_response` schema:
```json
{
  "job_id": "abc12345",
  "status": "pending",
  "active_goals": 0,
  "completed_goals": 0,
  "failed_goals": 0,
  "total_goals": 1,
  "total_tokens_used": 100,
  "total_duration_ms": 5000,
  "last_error": null,
  "worker_id": null,
  "created_at": "2026-06-16T07:30:00Z",
  "updated_at": "2026-06-16T07:30:00Z"
}
```

### Job-to-GoalNode Mapping

`Job.from_goal_node()` method converts GoalNode to Job facade:
- Validates root goal (parent_id=None)
- Maps GoalStatus to JobState
- Calculates guidance_count from guidance_accumulated length
- Accepts optional stats dict for descendant metrics

## Testing Coverage

23 unit tests covering:
- Lifecycle transitions (create, pause, resume, cancel)
- Terminal state validation errors
- Job not found scenarios
- Status queries with filtering
- Checkpoint persistence and restoration
- Orphaned checkpoint deletion
- Helper method correctness

All tests pass with zero lint errors.

## Integration Points

JobManager integrates with:
- **ContextEngine**: Goal creation, state transitions, queries
- **AsyncPersistStore**: Checkpoint persistence backend (SQLite/PostgreSQL)
- **AutopilotService**: Job submission and monitoring (future integration)
- **WebSocket Router**: IPC response building for RFC-228 commands

## Future Work

| Task | RFC Reference | Priority |
|------|---------------|----------|
| Wire JobManager into AutopilotService.startup | RFC-222 H4 | High |
| Job guidance absorption integration | RFC-228 §70 | Medium |
| Job retry policy enforcement | RFC-204 | Medium |
| Job deadline monitoring | RFC-222 H5 | Medium |

## Verification Results

```
✓ All lint checks passed (780 files)
✓ All unit tests passed (23 tests)
✓ verify_finally.sh passed (sync, lint, test)
✓ Import boundaries validated
✓ Zero unused imports
```

Ready for integration into daemon startup sequence.