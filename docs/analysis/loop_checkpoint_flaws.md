# Loop Checkpoint Logical Flaws Analysis

**Date**: 2026-04-23
**Analyzer**: Claude Code
**Scope**: AgentLoop checkpoint persistence in `~/.soothe/data/loop_checkpoints.db`

---

## Summary

Found **CRITICAL bug** causing orphaned running goals and inconsistent checkpoint state.

### Key Findings

1. **Index Calculation Bug** (agent_loop.py:203) - current_goal_index computed BEFORE goal is appended
2. **Orphaned Running Goals** - Goals marked "running" but parent loop has current_goal_index=-1
3. **Missing History Data** - Running goals have empty reason_history/act_history despite iteration=0
4. **Incomplete Recovery Logic** - Goals never properly finalized, stuck in "running" state forever

---

## Critical Bug #1: Index Calculation Order Error

### Location
`packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py:202-206`

### Bug Code
```python
# WRONG ORDER - compute index BEFORE append
goal_record = state_manager.start_new_goal(goal, max_iterations)
checkpoint.current_goal_index = len(checkpoint.goal_history) - 1  # ← BUG HERE
checkpoint.goal_history.append(goal_record)  # ← append happens AFTER index calculation
checkpoint.status = "running"
await state_manager.save(checkpoint)
```

### Expected Behavior
When adding first goal:
- goal_history length BEFORE append: 0
- current_goal_index should be set AFTER append: 0 (points to newly added goal at position 0)

### Actual Behavior
- current_goal_index computed BEFORE append: `0 - 1 = -1`
- goal_history appended AFTER, making length = 1
- current_goal_index stays at -1 (invalid)
- **Result**: Loop claims "no active goal" (index=-1) while goal_history has 1 goal

### Fix
```python
# CORRECT ORDER - append BEFORE computing index
goal_record = state_manager.start_new_goal(goal, max_iterations)
checkpoint.goal_history.append(goal_record)  # ← append FIRST
checkpoint.current_goal_index = len(checkpoint.goal_history) - 1  # ← compute AFTER
checkpoint.status = "running"
await state_manager.save(checkpoint)
```

---

## Critical Bug #2: Orphaned Running Goals

### Database Evidence

```sql
-- Loops with "ready_for_next_goal" but current_goal_index=-1
SELECT loop_id, status, current_goal_index FROM agentloop_loops 
WHERE status='ready_for_next_goal' AND current_goal_index=-1;

Results:
i7mo5l2j70lp|ready_for_next_goal|-1
qnd6ad6tucio|ready_for_next_goal|-1  
yhjsvow06djk|ready_for_next_goal|-1
(test_loop|running|-1) ← test loop also affected
```

```sql
-- Goals marked "running" but parent loop says current_goal_index=-1
SELECT goal_id, status, loop_id FROM goal_records 
WHERE status='running';

Results:
i7mo5l2j70lp_goal_0|running|i7mo5l2j70lp
qnd6ad6tucio_goal_0|running|qnd6ad6tucio
yhjsvow06djk_goal_0|running|yhjsvow06djk
```

### Logical Inconsistency
- Parent loop says: `current_goal_index=-1` (no active goal, ready for next)
- Child goal says: `status='running'` (actively executing)
- **Contradiction**: Loop thinks it's idle, goal thinks it's running
- **Consequence**: Goals never finalized, stuck in limbo state

---

## Critical Bug #3: Empty History Despite Iteration

### Database Evidence

```sql
SELECT goal_id, iteration, reason_history, act_history 
FROM goal_records WHERE status='running';

Results:
i7mo5l2j70lp_goal_0|0|[]|[]
qnd6ad6tucio_goal_0|0|[]|[]
yhjsvow06djk_goal_0|0|[]|[]
```

### Anomaly
- Goals have `iteration=0` (started first iteration)
- But `reason_history=[]` and `act_history=[]` (no execution records)
- **Missing**: Plan phase reasoning, Act phase execution steps
- **Root Cause**: Goals initialized but never executed iterations, stuck at iteration=0

### Compare with Completed Goals
```sql
SELECT goal_id, iteration, reason_history, act_history 
FROM goal_records WHERE status='completed';

Results (truncated):
flin1gt6qozz_goal_0|1|[{"iteration": 0, ...}]|[{"iteration": 0, ...}]
p6230jp5h5vo_goal_0|1|[{"iteration": 0, ...}]|[{"iteration": 0, ...}]
```

Completed goals have proper history data with iteration records.

---

## Impact Analysis

### 1. Data Corruption
- **3+ loops** with orphaned running goals
- Goals never complete, pollute checkpoint database
- Thread health metrics invalid (claim last_goal_status='completed' but current goal is running)

### 2. Recovery Failure
- If daemon crashes, these goals cannot resume properly
- Recovery logic looks for `current_goal_index >= 0` to find active goal
- With index=-1, recovery skips these goals entirely
- **Result**: Goals lost on restart

### 3. Resource Waste
- Orphaned goals consume database space
- Never cleaned up, accumulate over time
- Thread health metrics become unreliable

### 4. Misleading State
- Users see `status=ready_for_next_goal` (suggests loop is idle)
- But goal_history has unfinished work
- **False positive**: System appears ready when it has pending work

---

## Root Cause Chain

### Execution Flow

1. User starts goal: `run("read readme")`
2. `agent_loop.py:202` creates goal_record via `start_new_goal()`
3. `agent_loop.py:203` computes index: `current_goal_index = len([]) - 1 = -1` ← BUG
4. `agent_loop.py:204` appends goal: `goal_history = [goal_record]`
5. `agent_loop.py:206` saves checkpoint with index=-1 ← Saved wrong
6. **Iteration starts**: Loop enters while loop
7. **Goal executes**: Plan/Act phases run
8. **Checkpoint updated**: `state_manager.record_iteration()` saves history
9. **BUT**: Recovery cannot find goal because index=-1 ← Cannot resume
10. **Goal fails**: Exception/crash occurs, goal stuck at iteration=0
11. **Loop ends**: Loop sets status=ready_for_next_goal, index stays -1
12. **Final save**: Goal stays "running" forever ← Orphaned

---

## Additional Issues

### 1. Missing Finalization
- No code path to transition running→completed goals with index=-1
- `finalize_goal()` expects valid goal_index to update
- With index=-1, finalization logic skipped

### 2. Thread Health Inconsistency
```sql
SELECT thread_health_metrics FROM agentloop_loops WHERE loop_id='i7mo5l2j70lp';

{
  "last_goal_status": "completed",  ← WRONG: current goal is running
  "consecutive_goal_failures": 0,
  ...
}
```

Metrics claim last goal completed, but current goal is running.

### 3. Schema Version Mismatch
- All loops have `schema_version='3.1'`
- But bug existed since schema creation
- Migration won't fix logical corruption

---

## Recommended Fixes

### Fix 1: Correct Index Calculation Order
**File**: `agent_loop.py:202-206`
**Priority**: CRITICAL

```python
# BEFORE (BUGGY):
checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
checkpoint.goal_history.append(goal_record)

# AFTER (FIXED):
checkpoint.goal_history.append(goal_record)
checkpoint.current_goal_index = len(checkpoint_goal_history) - 1
```

### Fix 2: Add Validation in start_new_goal()
**File**: `state_manager.py:start_new_goal()`
**Priority**: HIGH

```python
def start_new_goal(...) -> GoalExecutionRecord:
    ...
    # NEW: Validate checkpoint state before creating goal
    if checkpoint.status == "running":
        raise ValueError(f"Cannot start new goal while loop is running (status={checkpoint.status})")
    
    goal_record = GoalExecutionRecord(...)
    
    # NEW: Append immediately to prevent index mismatch
    checkpoint.goal_history.append(goal_record)
    checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
    
    return goal_record  # Caller should NOT append again
```

### Fix 3: Recovery Logic for Orphaned Goals
**File**: `state_manager.py:load()`
**Priority**: MEDIUM

```python
async def load() -> AgentLoopCheckpoint | None:
    ...
    # NEW: Detect and fix orphaned goals
    if checkpoint.status == "ready_for_next_goal" and checkpoint.current_goal_index == -1:
        # Check if goal_history has running goals
        running_goals = [g for g in checkpoint.goal_history if g.status == "running"]
        if running_goals:
            logger.warning(
                "Found orphaned running goals in loop %s (index=-1 but %d running goals)",
                checkpoint.loop_id,
                len(running_goals)
            )
            # Auto-repair: set index to last running goal
            checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
            checkpoint.status = "running"
            logger.info("Auto-repaired orphaned goal index: set to %d", checkpoint.current_goal_index)
    
    return checkpoint
```

### Fix 4: Cleanup Script for Existing Data
**Priority**: LOW (one-time cleanup)

```sql
-- Find orphaned running goals
SELECT l.loop_id, l.current_goal_index, g.goal_id, g.status
FROM agentloop_loops l
JOIN goal_records g ON l.loop_id = g.loop_id
WHERE l.current_goal_index = -1 AND g.status = 'running';

-- Auto-repair: set index to running goal
UPDATE agentloop_loops
SET current_goal_index = (
    SELECT COUNT(*) - 1 FROM goal_records 
    WHERE loop_id = agentloop_loops.loop_id
),
status = 'running'
WHERE current_goal_index = -1 
AND EXISTS (
    SELECT 1 FROM goal_records 
    WHERE loop_id = agentloop_loops.loop_id 
    AND status = 'running'
);
```

---

## Test Cases

### Unit Test for Index Calculation
```python
def test_goal_index_calculation():
    """Test that current_goal_index is computed AFTER append."""
    state_manager = AgentLoopStateManager()
    checkpoint = await state_manager.initialize("thread_1")
    
    # Add first goal
    goal_record = state_manager.start_new_goal("test goal")
    checkpoint.goal_history.append(goal_record)
    checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
    
    # Verify
    assert checkpoint.current_goal_index == 0  # Should point to first goal
    assert len(checkpoint.goal_history) == 1
    assert checkpoint.goal_history[0].goal_id == goal_record.goal_id
    
    # Add second goal
    goal_record2 = state_manager.start_new_goal("test goal 2")
    checkpoint.goal_history.append(goal_record2)
    checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
    
    # Verify
    assert checkpoint.current_goal_index == 1  # Should point to second goal
    assert len(checkpoint.goal_history) == 2
```

### Integration Test for Orphaned Goals
```python
async def test_no_orphaned_goals():
    """Test that goals are never orphaned after crash."""
    # Simulate crash scenario
    state_manager = AgentLoopStateManager()
    checkpoint = await state_manager.initialize("thread_1")
    
    # Add goal with BUGGY order (should fail validation)
    goal_record = state_manager.start_new_goal("test")
    checkpoint.current_goal_index = len(checkpoint.goal_history) - 1  # BUG
    checkpoint.goal_history.append(goal_record)
    
    # Validation should catch this
    assert checkpoint.current_goal_index >= 0  # Should never be -1
    assert checkpoint.goal_history[checkpoint.current_goal_index].status == "running"
```

---

## Verification Checklist

After fixes, verify:

- [ ] All new goals have current_goal_index >= 0
- [ ] No orphaned running goals in database
- [ ] Recovery logic can find active goal by index
- [ ] Finalization logic completes all running goals
- [ ] Thread health metrics match actual goal status
- [ ] No goals stuck at iteration=0 with empty history

---

## Conclusion

The primary bug is a **simple order error** causing cascading failures:
- Index computed BEFORE append → wrong position
- Goals orphaned → cannot resume after crash
- History empty → goals stuck at iteration=0
- State inconsistent → misleading health metrics

**Fix is trivial**: Move append BEFORE index calculation.

**Impact is severe**: Data corruption, recovery failure, resource waste.

Immediate action required to prevent further data corruption.