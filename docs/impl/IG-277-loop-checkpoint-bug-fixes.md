# IG-053: Loop Checkpoint Index Calculation Bug Fixes

**Status**: ✅ Completed
**Date**: 2026-04-23
**RFC References**: RFC-608 (Multi-thread spanning), RFC-409 (Persistence backend)

---

## Summary

Fixed critical bug in AgentLoop checkpoint persistence causing orphaned running goals and inconsistent state. 

**Root Cause**: `current_goal_index` computed BEFORE goal appended to `goal_history`, resulting in index=-1 when history was empty.

**Impact**: 
- 3+ loops with orphaned running goals in production database
- Goals stuck at iteration=0 with empty execution history
- Recovery failures after daemon crashes
- Misleading state (loops claiming "ready_for_next_goal" but having running goals)

---

## Changes Made

### 1. Fix Index Calculation Order (agent_loop.py:202-206)

**Before**:
```python
goal_record = state_manager.start_new_goal(goal, max_iterations)
checkpoint.current_goal_index = len(checkpoint.goal_history) - 1  # ← BUG: computed BEFORE
checkpoint.goal_history.append(goal_record)  # ← appended AFTER
checkpoint.status = "running"
```

**After**:
```python
goal_record = state_manager.start_new_goal(goal, max_iterations)
checkpoint.goal_history.append(goal_record)  # ← Append FIRST
checkpoint.current_goal_index = len(checkpoint.goal_history) - 1  # ← Compute AFTER
checkpoint.status = "running"
```

**Impact**: Guarantees `current_goal_index >= 0` when goals exist.

---

### 2. Add Validation in start_new_goal() (state_manager.py:331-365)

Added validation to prevent starting new goal while loop is already running:

```python
# Validate: Cannot start new goal while loop is already running
if checkpoint.status == "running":
    raise ValueError(
        f"Cannot start new goal while loop is running (status={checkpoint.status}, "
        f"current_goal_index={checkpoint.current_goal_index})"
    )
```

**Impact**: Prevents invalid state transitions and multiple simultaneous running goals.

---

### 3. Add Auto-Repair Logic in load() (state_manager.py:225-245)

Added recovery logic to detect and repair orphaned running goals on load:

```python
# Auto-repair: Detect and fix orphaned running goals
if checkpoint.status == "ready_for_next_goal" and checkpoint.current_goal_index == -1:
    # Check if goal_history has running goals
    running_goals = [g for g in checkpoint.goal_history if g.status == "running"]
    if running_goals:
        logger.warning(
            "Found orphaned running goals in loop %s (index=-1 but %d running goals)",
            checkpoint.loop_id,
            len(running_goals),
        )
        # Auto-repair: set index to last running goal
        checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
        checkpoint.status = "running"
        logger.info("Auto-repaired orphaned goal index: set to %d", checkpoint.current_goal_index)
        # Save repaired checkpoint
        await self._save_checkpoint_to_db(checkpoint)
```

**Impact**: Automatically repairs corrupted checkpoints on recovery, preventing data loss.

---

### 4. Create Cleanup Script (scripts/fix_orphaned_goals.py)

Created standalone script to repair existing orphaned goals in production database:

**Features**:
- Detects orphaned running goals with index=-1
- Repairs by setting correct goal_index
- Dry-run mode (--dry-run) for verification
- Verification mode (--verify) to check repairs
- Detailed logging and reporting

**Usage**:
```bash
# Dry run (see what would be fixed)
python scripts/fix_orphaned_goals.py --dry-run

# Apply fixes
python scripts/fix_orphaned_goals.py --apply

# Verify repairs
python scripts/fix_orphaned_goals.py --verify
```

---

### 5. Add Comprehensive Tests (test_checkpoint_index_fix.py)

Created 14 test cases covering:

**TestIndexCalculationFix** (4 tests):
- First goal index is 0, not -1
- Second goal index is 1
- Index never negative across multiple goals
- Saved checkpoint preserves correct index

**TestValidationLogic** (2 tests):
- Cannot start goal while loop running
- Can start goal after finalize

**TestOrphanedGoalRecovery** (3 tests):
- Detects orphaned goals with index=-1
- Auto-repair sets correct index
- No repair if goals completed

**TestDatabaseConsistency** (2 tests):
- Goal history matches database
- No negative index after save

**TestEdgeCases** (3 tests):
- Empty goal history
- Single goal iteration
- Thread switch preserves index

**Results**: All 14 tests passing ✅

---

## Verification Results

### Pre-Fix Database State

```sql
-- Orphaned goals detected
SELECT loop_id, status, current_goal_index FROM agentloop_loops 
WHERE status='ready_for_next_goal' AND current_goal_index=-1;

Results: 3 loops with orphaned goals
- i7mo5l2j70lp (status=ready, index=-1, goal=running)
- qnd6ad6tucio (status=ready, index=-1, goal=running)
- yhjsvow06djk (status=ready, index=-1, goal=running)
```

### Post-Fix Verification

```bash
✓ Formatting check passed (310 files OK)
✓ Linting check passed (0 errors)
✓ Unit tests passed (1312 tests, including 14 new checkpoint tests)
✓ All verification checks passed
```

---

## Files Modified

### Core Fixes
- `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py` (index order fix)
- `packages/soothe/src/soothe/cognition/agent_loop/state_manager.py` (validation + auto-repair)

### New Files
- `scripts/fix_orphaned_goals.py` (cleanup script)
- `packages/soothe/tests/unit/cognition/agent_loop/test_checkpoint_index_fix.py` (14 tests)
- `docs/analysis/loop_checkpoint_flaws.md` (detailed analysis)
- `docs/impl/IG-053-loop-checkpoint-bug-fixes.md` (this document)

---

## Database Impact

### Immediate Effect

- **New goals**: All future goals will have correct `current_goal_index >= 0`
- **Existing orphaned goals**: Auto-repaired on next load via recovery logic
- **No data loss**: Orphaned goals recovered, not deleted

### Recommended Cleanup

Run cleanup script to repair existing orphaned goals:

```bash
python scripts/fix_orphaned_goals.py --apply --verify
```

---

## Testing Evidence

### Unit Test Coverage

```bash
$ pytest packages/soothe/tests/unit/cognition/agent_loop/test_checkpoint_index_fix.py -v

14 passed in 0.16s ✅

Key tests:
- test_first_goal_index_is_zero ✅
- test_index_never_negative ✅  
- test_detects_orphaned_goal ✅
- test_no_goals_with_negative_index_after_save ✅
```

### Integration Verification

```bash
$ ./scripts/verify_finally.sh

✓ Workspace setup
✓ Package dependency validation
✓ Code formatting check
✓ Linting check
✓ Unit tests (1312 passed)

All checks passed! Ready to commit ✅
```

---

## Lessons Learned

### Root Cause Analysis

Bug introduced at schema creation (schema_version='3.1') due to:
1. Order-dependent index calculation
2. No validation of state transitions
3. No recovery logic for corrupted state

### Prevention Measures

1. **Validation**: Prevent invalid state transitions (cannot start goal while running)
2. **Auto-repair**: Detect and fix corruption on recovery
3. **Comprehensive tests**: Cover edge cases and state transitions
4. **Cleanup script**: One-time repair for existing data

### Best Practices Enforced

- **Append before compute**: Always compute derived values AFTER modifying state
- **State machine validation**: Enforce valid state transitions
- **Recovery robustness**: Auto-repair corrupted state on load
- **Test edge cases**: Empty state, single item, multiple items

---

## References

- **RFC-608**: Multi-thread spanning with loop_id as primary key
- **RFC-409**: Unified global SQLite persistence backend
- **RFC-205**: AgentLoop checkpoint lifecycle management
- **Analysis**: `docs/analysis/loop_checkpoint_flaws.md`
- **Cleanup Script**: `scripts/fix_orphaned_goals.py`

---

## Next Steps

1. **Run cleanup script** on production database to repair existing orphaned goals
2. **Monitor checkpoint health** with `soothe doctor` command
3. **Verify after restart** that all loops recover correctly

---

## Conclusion

Critical bug fixed with comprehensive testing and recovery mechanisms. All verification checks passed. System now correctly manages goal indices and automatically repairs corrupted checkpoints on recovery.

**Ready to commit** ✅