# IG-134: Executor Thread Isolation Simplification

**Status**: Draft
**Spec traceability**: RFC-209 (Executor Thread Isolation Simplification)
**Platonic phase**: Implementation (IMPL) — code + tests + verification
**Dependencies**: RFC-201, RFC-100

---

## 1. Overview

This implementation guide simplifies Layer 2's executor by removing manual thread ID generation and leveraging langgraph's built-in concurrency handling and task tool's automatic subagent isolation.

**Impact**:
- Remove ~80 lines of thread management code
- Simplify executor to pure orchestration logic
- Eliminate manual merge operations
- Remove deprecated config flags and state fields

**No backward compatibility maintained** - complete removal of old patterns.

---

## 2. Implementation Plan

### Phase 1: Remove Thread Isolation Methods

**File**: `src/soothe/cognition/agent_loop/executor.py`

#### 1.1 Remove `_should_use_isolated_sequential_thread()`

```python
# DELETE THIS METHOD (lines 88-103)
def _should_use_isolated_sequential_thread(self, steps: list) -> bool:
    """Return True if sequential wave should use isolated thread.

    Semantic rule: isolate when any step delegates to subagent.
    Rationale: delegation steps should work on explicit input, not prior thread history.

    Args:
        steps: List of StepAction objects to execute

    Returns:
        True if thread isolation should be applied
    """
    if self._config is None or not self._config.agentic.sequential_act_isolated_thread:
        return False  # Feature disabled
    # Automatic: isolate if any step has subagent delegation
    return any(bool(getattr(s, "subagent", None)) for s in steps)
```

**Reason**: No longer needed. All executions use parent thread_id.

#### 1.2 Remove `_merge_isolated_act_into_parent_thread()`

```python
# DELETE THIS METHOD (lines 150-188)
async def _merge_isolated_act_into_parent_thread(
    self,
    *,
    parent_thread_id: str,
    child_thread_id: str,
) -> None:
    """Append messages from an isolated Act checkpoint branch onto the canonical thread."""
    graph = self.core_agent.graph
    cfg_child = {"configurable": {"thread_id": child_thread_id}}
    cfg_parent = {"configurable": {"thread_id": parent_thread_id}}
    try:
        snap = await graph.aget_state(cfg_child)
    except Exception:
        logger.debug(
            "Isolated Act merge skipped: failed to read child thread %s",
            child_thread_id,
            exc_info=True,
        )
        return
    if snap is None or not getattr(snap, "values", None):
        return
    msgs = snap.values.get("messages")
    if not msgs:
        logger.debug("Isolated Act merge skipped: no messages on child thread %s", child_thread_id)
        return
    try:
        await graph.aupdate_state(cfg_parent, {"messages": list(msgs)})
        logger.info(
            "Merged isolated sequential Act thread %s → %s (%d messages)",
            child_thread_id,
            parent_thread_id,
            len(msgs),
        )
    except Exception:
        logger.exception(
            "Failed merging isolated Act thread %s into parent %s",
            child_thread_id,
            parent_thread_id,
        )
```

**Reason**: No isolated threads created, no merge needed.

### Phase 2: Simplify Execution Logic

#### 2.1 Simplify `_execute_sequential_chunk()`

**File**: `src/soothe/cognition/agent_loop/executor.py` (lines 439-448)

```python
# BEFORE
act_thread_id = state.thread_id
isolated_child_id: str | None = None
if self._should_use_isolated_sequential_thread(steps):
    isolated_child_id = f"{state.thread_id}__l2act{uuid.uuid4().hex[:12]}"
    act_thread_id = isolated_child_id
    logger.info(
        "Sequential Act using isolated thread %s (merge → %s)",
        isolated_child_id,
        state.thread_id,
    )

# AFTER
act_thread_id = state.thread_id  # Always use parent thread_id
```

Also remove the merge call (lines 470-474):
```python
# DELETE
if isolated_child_id is not None:
    await self._merge_isolated_act_into_parent_thread(
        parent_thread_id=state.thread_id,
        child_thread_id=isolated_child_id,
    )
```

#### 2.2 Simplify `_execute_parallel()`

**File**: `src/soothe/cognition/agent_loop/executor.py` (lines 325-350)

```python
# BEFORE
tasks = [
    asyncio.create_task(
        self._execute_step_collecting_events(step, f"{state.thread_id}__step_{i}", state.workspace)
    )
    for i, step in enumerate(steps)
]

# AFTER
tasks = [
    asyncio.create_task(
        self._execute_step_collecting_events(step, state.thread_id, state.workspace)
    )
    for step in steps
]
```

#### 2.3 Update `_execute_step_collecting_events()` error handling

**File**: `src/soothe/cognition/agent_loop/executor.py` (lines 373-384)

```python
# BEFORE
step_result = StepResult(
    step_id=steps[i].id,
    success=False,
    error=str(result),
    error_type=self._classify_error_severity(result),
    duration_ms=0,
    thread_id=f"{state.thread_id}__step_{i}",
    subagent_task_completions=0,
    hit_subagent_cap=False,
)

# AFTER
step_result = StepResult(
    step_id=steps[i].id,
    success=False,
    error=str(result),
    error_type=self._classify_error_severity(result),
    duration_ms=0,
    thread_id=state.thread_id,  # Use parent thread_id
    subagent_task_completions=0,
    hit_subagent_cap=False,
)
```

### Phase 3: Remove State Fields

#### 3.1 Update `LoopState`

**File**: `src/soothe/cognition/agent_loop/schemas.py`

```python
# DELETE THIS FIELD
class LoopState(BaseModel):
    # ... existing fields ...
    act_will_have_checkpoint_access: bool = True  # REMOVE
```

#### 3.2 Remove checkpoint access logic

**File**: `src/soothe/cognition/agent_loop/executor.py` (lines 215-225)

```python
# DELETE THIS BLOCK
if decision.execution_mode == "sequential":
    has_delegation = any(bool(getattr(s, "subagent", None)) for s in ready_steps)
    isolation_enabled = self._config is not None and self._config.agentic.sequential_act_isolated_thread
    state.act_will_have_checkpoint_access = not (has_delegation and isolation_enabled)
elif decision.execution_mode in ("parallel", "dependency"):
    state.act_will_have_checkpoint_access = False
else:
    state.act_will_have_checkpoint_access = True
```

### Phase 4: Update Reason Phase

#### 4.1 Remove conditional logic in reason.py

**File**: `src/soothe/cognition/agent_loop/reason.py`

Find and remove any logic checking `state.act_will_have_checkpoint_access`. Prior conversation should always be injected (same thread_id).

### Phase 5: Update Config

#### 5.1 Remove from SootheConfig

**File**: `src/soothe/config/config.py`

Remove field:
```python
class AgenticLoopConfig(BaseModel):
    sequential_act_isolated_thread: bool = False  # REMOVE
```

#### 5.2 Update config files

**File**: `config/config.yml` (template)

```yaml
# DELETE THIS LINE
agentic:
  sequential_act_isolated_thread: true
```

**File**: `config.dev.yml`

```yaml
# DELETE THIS LINE
agentic:
  sequential_act_isolated_thread: true
```

### Phase 6: Update Runner Code

#### 6.1 Update `_runner_steps.py`

**File**: `src/soothe/core/runner/_runner_steps.py`

Find:
```python
step_tid = f"{state.thread_id}__step_{s.id}"
```

Replace with:
```python
step_tid = state.thread_id  # Use parent thread_id
```

---

## 3. Testing Strategy

### 3.1 Run Existing Tests

```bash
./scripts/verify_finally.sh
```

Expected: All 900+ tests pass.

### 3.2 Specific Test Cases to Verify

1. **Parallel execution**: Multiple file reads in parallel
   - Verify: No conflicts, results merge correctly
   - Test file: `tests/unit/test_executor_parallel.py`

2. **Sequential with subagent**: Research then write
   - Verify: task tool isolates subagent, results merge
   - Test file: `tests/unit/test_executor_sequential.py`

3. **Dependency mode**: DAG execution with concurrent waves
   - Verify: Dependencies respected, no race conditions
   - Test file: `tests/unit/test_executor_dependency.py`

### 3.3 Performance Benchmarks

Measure before/after:
- Context token usage (should decrease - no isolated thread duplication)
- Execution latency (should improve - no merge overhead)
- Memory footprint (should decrease - fewer thread branches)

---

## 4. Files Changed

| File | Change Type | Lines Changed |
|------|-------------|---------------|
| `src/soothe/cognition/agent_loop/executor.py` | Simplify | -80 lines |
| `src/soothe/cognition/agent_loop/schemas.py` | Remove field | -1 line |
| `src/soothe/cognition/agent_loop/reason.py` | Simplify | -5 lines |
| `src/soothe/config/config.py` | Remove field | -1 line |
| `config/config.yml` | Remove config | -1 line |
| `config.dev.yml` | Remove config | -1 line |
| `src/soothe/core/runner/_runner_steps.py` | Simplify | -1 line |

**Total**: ~90 lines removed

---

## 5. Verification Checklist

- [ ] Remove `_should_use_isolated_sequential_thread()` method
- [ ] Remove `_merge_isolated_act_into_parent_thread()` method
- [ ] Simplify `_execute_sequential_chunk()` thread ID logic
- [ ] Simplify `_execute_parallel()` thread ID logic
- [ ] Remove `act_will_have_checkpoint_access` from LoopState
- [ ] Remove checkpoint access logic from executor
- [ ] Update reason.py to remove conditional logic
- [ ] Remove `sequential_act_isolated_thread` from config
- [ ] Update config files
- [ ] Update _runner_steps.py
- [ ] Run all tests (900+)
- [ ] Verify no performance regression
- [ ] Update inline code comments

---

## 6. Success Criteria

1. ✅ All tests pass (900+)
2. ✅ No manual thread ID generation in executor
3. ✅ No merge logic remaining
4. ✅ Config flags removed
5. ✅ ~80-90 lines of code removed
6. ✅ Performance maintained or improved
7. ✅ Thread safety verified through testing

---

## 7. Rollback Plan

If issues arise, revert commit and restore:
1. `_should_use_isolated_sequential_thread()` method
2. `_merge_isolated_act_into_parent_thread()` method
3. Thread ID generation logic
4. Config flags

However, since this is a simplification, issues are unlikely. The new design is cleaner and trusts langgraph's proven concurrency model.

---

## 8. Related Documents

- RFC-209: Executor Thread Isolation Simplification
- RFC-201: Layer 2 Agentic Goal Execution
- RFC-100: Layer 1 CoreAgent Runtime
- IG-131: DEPRECATED - Sequential Act isolated thread
- IG-133: DEPRECATED - Avoid prior conversation duplication
- Design draft: `docs/drafts/2026-04-09-thread-isolation-simplification-design.md`

---

**Status**: Ready for implementation
**Estimated effort**: 2-3 hours
**Risk level**: Low (simplification, well-tested concurrency model)