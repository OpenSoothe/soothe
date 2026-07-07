# IG-133: Conditional Injection of Prior Conversation to Avoid Duplication

**Status:** DEPRECATED - Superseded by RFC-209  
**Updated:** 2026-04-12 (terminology refactoring per IG-153)

This implementation guide is superseded by RFC-209 (Executor Thread Isolation Simplification), which eliminates the need for conditional prior conversation injection. With RFC-209:

- All executions use parent thread_id (no isolated threads created manually)
- Prior conversation is always available via checkpoint (no need for conditional logic)
- The `execute_will_have_checkpoint_access` flag becomes unnecessary and will be removed
- Duplication is avoided naturally without conditional injection

**No backward compatibility maintained**. Once RFC-209 is implemented, this guide becomes obsolete.

**Spec traceability:** RFC-201 (Layer 2 Agentic Goal Execution), RFC-100 (CoreAgent Runtime)
**Platonic phase:** Implementation (IMPL) — superseded by architectural simplification

---

## 1. Overview

This guide eliminates duplication of prior thread messages between Plan prompts and CoreAgent execution contexts. Currently, `<SOOTHE_PRIOR_CONVERSATION>` is injected into Plan prompts unconditionally, but CoreAgent execution often loads the same messages from checkpoint history, causing token overhead and model confusion.

---

## 2. Problem Statement

### 2.1 Current Behavior

**Plan Phase:**
1. Loads recent messages from checkpointer (limit=16)
2. Formats them as `plan_conversation_excerpts`
3. Injects into Plan prompt via `<SOOTHE_PRIOR_CONVERSATION>` section

**Execute Phase:**
1. CoreAgent `astream()` is called with a `thread_id`
2. LangGraph automatically loads checkpoint state for that thread
3. Checkpoint contains all prior messages from the thread

### 2.2 Duplication Scenarios

| Scenario | Thread ID in Act | Checkpoint History | Prior Conversation in Reason | Duplication? |
|----------|------------------|--------------------|------------------------------|--------------|
| Sequential tool-only | Canonical `thread_id` | ✅ Full history loaded | ✅ Injected | **YES** ❌ |
| Sequential delegation (isolated) | `{thread_id}__l2act{uuid}` | ❌ Fresh/empty | ✅ Injected | **NO** ✅ |
| Parallel execution | `{thread_id}__step_{i}` | ❌ Empty per step | ✅ Injected | **NO** ✅ |

**Impact of Duplication:**
- Token overhead: 16 messages counted twice (~8k-16k tokens)
- Model confusion: Same content in two different contexts
- Cost: Unnecessary token usage
- Reduced effective context window

---

## 3. Solution Design

### 3.1 Conditional Injection Logic

Inject `<SOOTHE_PRIOR_CONVERSATION>` only when Execute execution **won't have checkpoint history access**:

```python
# Determine if Execute will have checkpoint access
will_have_checkpoint_access = (
    execution_mode == "sequential"
    and not any(step.subagent for step in steps)  # Tool-only
    and config.agentic.sequential_execute_isolated_thread is False  # Isolation disabled
)

# Only inject prior conversation if checkpoint won't be loaded
if context.recent_messages and not will_have_checkpoint_access:
    parts.append("<SOOTHE_PRIOR_CONVERSATION>...")
```

### 3.2 Decision Matrix

| Execution Mode | Has Subagent? | Isolation Enabled? | Inject Prior Conversation? |
|----------------|---------------|--------------------|----------------------------|
| Sequential | No | False | **NO** (checkpoint loaded) |
| Sequential | No | True | **NO** (checkpoint loaded if no subagent) |
| Sequential | Yes | True | **YES** (isolated thread, no checkpoint) |
| Sequential | Yes | False | **NO** (checkpoint loaded) |
| Parallel | Any | Any | **YES** (isolated threads per step) |
| Dependency | Any | Any | **YES** (parallel execution with isolation) |

### 3.3 Rationale

**Why not inject when checkpoint is available?**
- CoreAgent already loads messages from checkpoint
- Model receives messages in context window automatically
- Adding them to Reason prompt creates redundancy

**Why inject when checkpoint is unavailable?**
- Isolated threads have no prior history
- Prior conversation is essential for follow-up tasks (e.g., "translate that")
- No other way for model to know prior context

---

## 4. Implementation Plan

### 4.1 Changes Required

**1. Add execution context flag to LoopState**

`src/soothe/cognition/agent_loop/schemas.py`:
```python
class LoopState(BaseModel):
    # ... existing fields ...

    # Execution context flag (set by Executor before Plan phase)
    execute_will_have_checkpoint_access: bool = True
```

**2. Update Executor to set the flag**

`src/soothe/cognition/agent_loop/executor.py`:
```python
async def execute(self, decision: AgentDecision, state: LoopState):
    # Determine if Execute will have checkpoint access
    if decision.execution_mode == "sequential":
        has_delegation = any(step.subagent for step in decision.steps)
        isolation_enabled = self._config.agentic.sequential_execute_isolated_thread
        state.execute_will_have_checkpoint_access = not (has_delegation and isolation_enabled)
    elif decision.execution_mode in ("parallel", "dependency"):
        state.execute_will_have_checkpoint_access = False  # Isolated threads
    else:
        state.execute_will_have_checkpoint_access = True  # Default to True
```

**3. Update Plan prompt builder to conditionally inject**

`src/soothe/cognition/planning/simple.py`:
```python
# Only inject prior conversation if Execute won't load checkpoint
if context.recent_messages and not state.execute_will_have_checkpoint_access:
    parts.append("\n<SOOTHE_PRIOR_CONVERSATION>\n")
    parts.append(
        "Recent messages in this thread before the current goal. The user may refer to this content "
        '(e.g. "translate that", "summarize the above", "shorter").\n'
    )
    parts.extend(context.recent_messages)
    parts.append(
        "\n<SOOTHE_FOLLOW_UP_POLICY>\n"
        '- If the goal depends on this prior text, status MUST NOT be "done" until CoreAgent execution '
        "has produced the requested output (translation, summary, etc.).\n"
        '- With plan_action "new", include at least one concrete execute_steps item that performs the work '
        "(e.g. invoke the main assistant to translate or rewrite the relevant excerpt).\n"
        "- Do not claim the task is finished in user_summary unless the evidence or step output contains "
        "the actual result.\n"
        "</SOOTHE_FOLLOW_UP_POLICY>\n"
        "</SOOTHE_PRIOR_CONVERSATION>\n"
    )
```

### 4.2 Files Affected

| File | Changes |
|------|---------|
| `src/soothe/cognition/agent_loop/schemas.py` | Add `execute_will_have_checkpoint_access` field to LoopState |
| `src/soothe/cognition/agent_loop/executor.py` | Set flag based on execution mode and isolation |
| `src/soothe/cognition/planning/simple.py` | Conditional injection in `build_loop_plan_prompt()` |

---

## 5. Testing Strategy

### 5.1 Unit Tests

**Test 1: Flag is set correctly**
- File: `tests/unit/test_executor_checkpoint_access_flag.py`
- Test cases:
  - Sequential tool-only → `execute_will_have_checkpoint_access = True`
  - Sequential delegation (isolation enabled) → `execute_will_have_checkpoint_access = False`
  - Parallel execution → `execute_will_have_checkpoint_access = False`
  - Dependency execution → `execute_will_have_checkpoint_access = False`

**Test 2: Prior conversation conditional injection**
- File: `tests/unit/test_plan_prior_conversation_conditional.py`
- Test cases:
  - Flag=False → prior conversation injected
  - Flag=True → prior conversation NOT injected
  - Empty recent_messages → no injection regardless of flag

### 5.2 Integration Tests

**Scenario 1: Tool-only sequential execution**
- Goal: "Execute command" (tool-only step)
- Verify: Plan prompt does NOT include `<SOOTHE_PRIOR_CONVERSATION>`
- Verify: CoreAgent loads checkpoint history normally

**Scenario 2: Delegation sequential execution (isolated)**
- Goal: "Translate to Chinese" (subagent step)
- Verify: Plan prompt INCLUDES `<SOOTHE_PRIOR_CONVERSATION>`
- Verify: CoreAgent runs on isolated thread without prior history

**Scenario 3: Mixed steps in sequential mode**
- Goal: Multi-step plan with both tool and subagent steps
- Verify: Injection decision based on first wave's execution characteristics

---

## 6. Token Savings Estimation

### 6.1 Before Implementation

**Duplication scenario (tool-only sequential):**
- Reason prompt: 16 messages × ~500 tokens = ~8,000 tokens
- CoreAgent context: Same 16 messages = ~8,000 tokens
- Total: ~16,000 tokens for the same content

### 6.2 After Implementation

**No duplication:**
- Reason prompt: 0 tokens (no prior conversation injected)
- CoreAgent context: 16 messages = ~8,000 tokens
- Total: ~8,000 tokens
- **Savings: ~8,000 tokens per iteration**

### 6.3 Impact

For a typical 4-iteration agentic loop:
- **Before:** ~64,000 tokens on prior conversation duplication
- **After:** ~32,000 tokens
- **Reduction: 50% token overhead for prior conversation**

---

## 7. Edge Cases and Considerations

### 7.1 First Iteration

**Issue:** First iteration has no prior conversation anyway.

**Solution:** The `context.recent_messages` will be empty, so no injection regardless of flag. No special handling needed.

### 7.2 Isolation Disabled Globally

**Issue:** If `sequential_act_isolated_thread` is False, delegation steps use canonical thread.

**Solution:** Flag will be True (checkpoint access), so prior conversation won't be injected. This is correct behavior - CoreAgent will load checkpoint history.

### 7.3 Mixed Execution Modes

**Issue:** Plan changes between iterations (e.g., delegation in iteration 1, tool-only in iteration 2).

**Solution:** Flag is recomputed for each execution wave based on current `AgentDecision`. Prior conversation injection adapts dynamically.

### 7.4 Empty Recent Messages

**Issue:** Thread has no prior history.

**Solution:** `context.recent_messages` is empty list, injection is skipped naturally.

---

## 8. Backward Compatibility

### 8.1 No Breaking Changes

- New field in LoopState with default value (`True`) maintains existing behavior
- Existing Reason prompts work unchanged when flag is True
- Only optimization when flag is False (no data loss)

### 8.2 Migration Path

No migration needed. The change is additive and purely optimization-focused.

---

## 9. Verification

After implementation:

```bash
./scripts/verify_finally.sh
```

Expected:
- All existing tests pass
- New unit tests pass (flag behavior, conditional injection)
- No increase in test failures

---

## 10. Documentation Updates

**Update RFC-201** to document the conditional injection behavior:

```
### Prior Conversation Injection

Layer 2 Plan prompts include prior thread conversation only when necessary:

- **Injected when:** Execute execution uses isolated thread (no checkpoint access)
- **Not injected when:** Execute execution uses canonical thread (checkpoint loaded automatically)

This avoids duplication and reduces token overhead by ~50% for follow-up goals.
```

---

## 11. Success Criteria

1. ✅ No duplication of prior messages between Reason prompt and CoreAgent context
2. ✅ Token overhead reduced by ~50% for tool-only sequential execution
3. ✅ Prior conversation still available for isolated execution scenarios
4. ✅ All tests pass
5. ✅ No breaking changes to existing behavior

---

## 12. Related Specifications

| RFC/IG | Relevance |
|--------|-----------|
| RFC-201 | Layer 2 agentic goal execution |
| RFC-100 | CoreAgent runtime (checkpoint loading) |
| IG-131 | Sequential Act isolated thread pattern |
| IG-128 | Prior conversation for Reason |
| IG-132 | Layer 2 context isolation completion |

---

## 13. Changelog

**2026-04-08 (created)**:
- IG-133 initial draft
- Identified duplication problem between Reason prompt and checkpoint
- Designed conditional injection logic
- Planned implementation and testing strategy