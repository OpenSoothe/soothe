# RFC-625 Phase 3 Migration Plan: GoalEngine → ContextEngine

**Created**: 2026-06-15
**Status**: Draft - Pending Approval
**RFC**: 625

---

## Overview

This plan details the migration from GoalEngine to ContextEngine as the sole source of truth for goal/step state, per RFC-625. The migration involves:

1. Enhancing ContextEngine with missing GoalEngine methods
2. Updating AutopilotService to use ContextEngine + AutopilotMonitor
3. Updating daemon core.py initialization
4. Removing runner GoalEngine references
5. Deleting GoalEngine and FileLockRegistry
6. Updating tests

---

## Gap Analysis: GoalEngine → ContextEngine Methods

### ✅ Already in ContextEngine (No Changes Needed)

| GoalEngine Method | ContextEngine Equivalent |
|-------------------|------------------------|
| `create_goal()` | `create_goal()` ✓ |
| `get_goal()` | `get_goal()` / `get_goal_sync()` ✓ |
| `list_goals()` | `list_goals()` ✓ |
| `complete_goal()` | `complete_goal()` ✓ |
| `cancel_goal()` | `cancel_goal()` ✓ |
| `suspend_goal()` | `suspend_goal()` ✓ |
| `block_goal()` | `block_goal()` ✓ |
| `unblock_goal()` | `unblock_goal()` ✓ |
| `is_complete()` | `is_dag_complete()` ✓ |
| `recover_active_goals()` | `recover()` ✓ |
| Snapshot persistence | `save()` / `load()` ✓ |

### ❌ Missing in ContextEngine (Need to Add)

| GoalEngine Method | Purpose | Priority |
|-------------------|---------|----------|
| `peek_ready_goals(limit)` | Scheduler: get ready candidates without mutation | **Critical** |
| `claim_goal(goal_id, loop_id)` | Atomically activate for dispatch | **Critical** |
| `fail_goal(id, evidence)` | Current signature uses `error: str`, needs `EvidenceBundle` | **Critical** |
| `send_back_goal(id, reason)` | RFC-204 consensus send-back | High |
| `validate_goal(id)` | RFC-204 acceptance validation | High |
| `reactivate_goal(id)` | RFC-204 resume suspended/blocked | High |
| `check_reactivated_goals()` | RFC-204 auto-reactivate on deps resolved | Medium |
| `mark_awaiting_clarification()` | RFC-622 pause for clarification | High |
| `answer_clarification()` | RFC-622 resume with answers | High |
| `absorb_guidance()` | RFC-228 accumulate LOR guidance | Medium |
| `apply_directives()` | RFC-204 Group C directive handling | High |

---

## Phase 3a: Enhance ContextEngine

### Files to Modify

- `packages/soothe/src/soothe/context/engine.py`
- `packages/soothe/src/soothe/context/models.py`

### New Methods to Add to ContextEngine

```python
class ContextEngine:
    # ── Scheduler methods (RFC-625) ────────────────────────────────

    def peek_ready_goals(self, limit: int = 1) -> list[GoalNode]:
        """Return ready candidates without mutation (read-only)."""

    async def claim_goal(self, goal_id: str, loop_id: str | None = None) -> GoalNode | None:
        """Atomically transition goal to active (dispatch claim)."""

    # ── RFC-204 methods ────────────────────────────────────────────

    async def send_back_goal(self, goal_id: str, reason: str = "") -> GoalNode:
        """Return goal to pending after consensus rejection."""

    async def validate_goal(self, goal_id: str) -> GoalNode:
        """Mark goal as validated (Layer 3 accepted)."""

    async def reactivate_goal(self, goal_id: str) -> GoalNode:
        """Reactivate suspended/blocked goal to pending."""

    async def check_reactivated_goals(self) -> list[GoalNode]:
        """Auto-reactivate goals whose deps are now resolved."""

    async def apply_directives(self, directives: list[GoalDirective], source_goal_id: str) -> list[str]:
        """Apply goal directives from completion chunk."""

    # ── RFC-622 clarification ───────────────────────────────────────

    async def mark_awaiting_clarification(self, goal_id: str, pending: dict, reason: str) -> GoalNode:
        """Pause goal awaiting clarification."""

    async def answer_clarification(self, goal_id: str, answers: list[str]) -> GoalNode:
        """Resume goal with clarification answers."""

    # ── RFC-228 guidance ────────────────────────────────────────────

    def absorb_guidance(self, goal_id: str, guidance_text: str, scope: str) -> bool:
        """Accumulate LOR guidance for goal."""

    # ── Modified fail_goal signature ─────────────────────────────────

    async def fail_goal(self, goal_id: str, evidence: EvidenceBundle | None = None, allow_retry: bool = True) -> BackoffDecision | None:
        """Fail goal with evidence bundle, trigger backoff reasoning."""
```

### GoalStepDAG Helper Methods to Add

```python
class GoalStepDAG:
    def peek_ready(self, limit: int, exclude_conflicts_with: set[str]) -> list[GoalNode]:
        """Filter pending goals whose deps are terminal, sorted by priority."""

    def claim(self, goal_id: str, loop_id: str | None) -> GoalNode | None:
        """Atomic claim with conflict re-check."""
```

---

## Phase 3b: Update AutopilotService

### File to Modify

- `packages/soothe/src/soothe/autopilot/service.py`

### Changes

1. **Constructor signature change:**
   ```python
   # Before
   def __init__(self, goal_engine: GoalEngine, config: AutonomousConfig, ...)

   # After
   def __init__(self, ce: ContextEngine, config: AutonomousConfig, ..., monitor: AutopilotMonitor | None = None)
   ```

2. **Replace field:**
   ```python
   # Before
   self._goal_engine: GoalEngine

   # After
   self._ce: ContextEngine
   self._monitor: AutopilotMonitor | None = monitor
   ```

3. **Remove FileLockRegistry references:**
   - Delete `_release_goal_locks()` method (FileLockRegistry deleted)
   - Delete `_release_loop()` file lock release code
   - WorkspaceReservation handles workspace conflicts (unchanged)

4. **Update method calls throughout:**
   - `_goal_engine.create_goal()` → `_ce.create_goal()`
   - `_goal_engine.peek_ready_goals()` → `_ce.peek_ready_goals()`
   - `_goal_engine.claim_goal()` → `_ce.claim_goal()`
   - `_goal_engine.fail_goal()` → `_ce.fail_goal()`
   - `_goal_engine.complete_goal()` → `_ce.complete_goal()`
   - `_goal_engine.file_registry` → **DELETE**
   - `_goal_engine.is_complete()` → `_ce.is_dag_complete()`

5. **Update docstrings:**
   - Remove references to GoalEngine
   - Document ContextEngine as source of truth

---

## Phase 3c: Update daemon core.py

### File to Modify

- `packages/soothe-daemon/src/soothe_daemon/server/core.py`

### Changes

```python
# Before
from soothe.autopilot import GoalEngine
daemon_goal_engine = GoalEngine(...)

# After
from soothe.context import ContextEngine
from soothe.autopilot import AutopilotMonitor

daemon_ce = ContextEngine(...)
daemon_monitor = AutopilotMonitor(ce=daemon_ce, bus=daemon_autopilot_bus, config=self._config)

self._autopilot_service = AutopilotService(
    ce=daemon_ce,
    config=self._config.agent.autonomous,
    monitor=daemon_monitor,
    ...
)
```

---

## Phase 3d: Remove Runner GoalEngine References

### Files to Modify

- `packages/soothe/src/soothe/runner/__init__.py`
- `packages/soothe/src/soothe/runner/resolver/_resolver_tools.py`

### Changes

1. **Delete `resolve_goal_engine()` function** from `_resolver_tools.py`
2. **Remove `_goal_engine` field** from SootheRunner
3. **Remove `resolve_goal_engine` import** from runner/__init__.py
4. **Remove TYPE_CHECKING import** of GoalEngine

---

## Phase 3e: Delete GoalEngine Files

### Files to Delete

| File | Lines | Action |
|------|-------|--------|
| `foundation/autopilot/engine.py` | 1821 | DELETE |
| `foundation/autopilot/file_lock_registry.py` | 270 | DELETE |
| `foundation/autopilot/backoff_reasoner.py` | 232 | DELETE (migrated to monitor/) |

### Files to Modify (Remove exports)

| File | Changes |
|------|---------|
| `foundation/autopilot/__init__.py` | Remove `GoalEngine`, `FileLockRegistry`, `GoalBackoffReasoner` exports; Keep `GoalDispatchContextBundle`, `EvidenceBundle`, `BackoffDecision`, `GoalStatus` |
| `foundation/autopilot/__init__.py` | Remove `GoalEngine` export |
| `foundation/__init__.py` | Remove `GoalEngine` export |

### Files to Keep (models.py cleanup)

- `foundation/autopilot/models.py` — Keep but **remove `Goal` class**:
  - Keep: `GoalStatus`, `TERMINAL_STATES`, `BLOCKED_STATES`
  - Keep: `EvidenceBundle`, `BackoffDecision`, `GoalSubDAGStatus`
  - Keep: `GoalDispatchContextBundle`, `GoalDispatchContextContribution`
  - Keep: `PriorStepSummary`, `FileTouchSummary`, `ParentFinding`, `Finding`, etc.
  - **DELETE**: `Goal` class (fields migrated to GoalNode)

---

## Phase 3f: Update Tests

### Test Files to DELETE

- `packages/soothe/tests/unit/core/goal_engine/` — **Delete entire directory** (10 files)
- `packages/soothe/tests/integration/core/goal_engine/` — **Delete entire directory** (1 file)
- `packages/soothe/tests/unit/middleware/test_file_lock.py` — Delete (FileLockRegistry deleted)
- `packages/soothe/tests/unit/core/goal_engine/test_file_lock_registry.py` — Already in deleted dir

### Test Files to UPDATE

| File | Changes |
|------|---------|
| `tests/unit/core/autopilot/test_submit_task.py` | Import ContextEngine instead of GoalEngine |
| `tests/unit/core/autopilot/test_real_dispatch.py` | Import ContextEngine |
| `tests/unit/core/autopilot/test_cancel_goal.py` | Import ContextEngine |
| `tests/unit/core/autopilot/test_subscribe_to_bus.py` | Import ContextEngine |
| `tests/unit/core/autopilot/test_deadline_monitor.py` | Import ContextEngine |
| `tests/unit/core/autopilot/test_consensus_dispatch.py` | Import ContextEngine |
| `tests/unit/core/autopilot/test_worker_pool.py` | Update Goal → GoalNode imports |
| `tests/unit/core/test_relationship_detector.py` | Update imports |
| `tests/unit/core/goal_engine/test_semantic_relationship_detector.py` | Move to different location or update |

---

## Models Migration Summary

### Goal → GoalNode (Already Done in Phase 2)

All `Goal` fields have been migrated to `GoalNode` in `foundation/context/models.py`:
- retry_count, max_retries, send_back_count, max_send_backs
- source_file, workspace, attempts_after_crash
- pending_clarification, guidance_accumulated
- report (serialized form)

### EvidenceBundle (Keep in engine/models.py)

Used by:
- AutopilotMonitor (backoff_reasoner)
- AutopilotService (fail_goal calls)
- StrangeLoop worker (GoalCompletionChunk)

### GoalDispatchContextBundle (Keep in engine/models.py)

Used by:
- AutopilotService `_build_merged_context()`
- ContextProjector
- Worker dispatch envelope

---

## Implementation Order

1. **Step 1**: Add missing methods to ContextEngine (Phase 3a)
2. **Step 2**: Update AutopilotService to use ContextEngine (Phase 3b)
3. **Step 3**: Update daemon core.py (Phase 3c)
4. **Step 4**: Run tests to verify migration works
5. **Step 5**: Remove runner GoalEngine references (Phase 3d)
6. **Step 6**: Delete Goal class from models.py
7. **Step 7**: Delete GoalEngine, FileLockRegistry files (Phase 3e)
8. **Step 8**: Delete goal_engine test directory (Phase 3f)
9. **Step 9**: Update remaining test imports (Phase 3f)
10. **Step 10**: Run `./scripts/verify_finally.sh`

---

## Risk Assessment

### High Risk Areas

1. **EvidenceBundle signature change** — `fail_goal()` needs to accept EvidenceBundle
2. **Scheduler logic** — `peek_ready_goals()` and `claim_goal()` are core to dispatch
3. **Conflict detection** — `conflicts_with` check in claim_goal
4. **Event emission** — State change events must continue flowing through bus

### Mitigation

- Implement ContextEngine methods by adapting GoalEngine code
- Keep identical signatures where possible
- Test scheduler behavior before deleting GoalEngine
- Monitor event bus emissions in integration tests

---

## Questions for User

1. Should we preserve the `file_registry` functionality in any form, or fully rely on WorkspaceReservation per RFC-625?
2. The `backoff_reasoner.py` in monitor/ already exists — should we delete engine/backoff_reasoner.py immediately or verify they're equivalent first?
3. Should `apply_directives()` live in ContextEngine or in AutopilotMonitor (RFC-625 says directives flow through Monitor)?