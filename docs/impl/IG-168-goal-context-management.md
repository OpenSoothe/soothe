# IG-168: Goal Context Management Implementation

**Implementation Guide**: IG-168
**RFC**: RFC-609
**Title**: Goal Context Management for AgentLoop
**Status**: In Progress
**Created**: 2026-04-17

## Overview

Implement unified goal-level context management for AgentLoop following RFC-609. Create GoalContextManager module that provides previous goal summaries for Plan phase (always) and Execute phase (thread switch only), maintaining architectural isolation between loop history and thread conversation.

## Dependencies

- RFC-609 (this implementation)
- RFC-200 (Agentic Goal Execution)
- RFC-608 (Multi-Thread Lifecycle)
- RFC-203 (Layer 2 Unified State Model)

## Implementation Scope

### Files to Create

- `packages/soothe/src/soothe/cognition/agent_loop/goal_context_manager.py` (NEW)

### Files to Modify

- `packages/soothe/src/soothe/cognition/agent_loop/checkpoint.py` (add thread_switch_pending)
- `packages/soothe/src/soothe/cognition/agent_loop/state_manager.py` (set flag in execute_thread_switch)
- `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py` (inject goal context)
- `packages/soothe/src/soothe/cognition/agent_loop/executor.py` (inject briefing config)
- `packages/soothe/src/soothe/config/models.py` (add GoalContextConfig)
- `packages/soothe/src/soothe/config/config.yml` (add goal_context section)
- `config/config.dev.yml` (add goal_context defaults)

### Files to Test

- `packages/soothe/tests/unit/cognition/agent_loop/test_goal_context_manager.py` (NEW)
- `packages/soothe/tests/integration/cognition/agent_loop/test_goal_context_integration.py` (NEW)

## Implementation Steps

### Step 1: Create GoalContextManager Module

**File**: `goal_context_manager.py`

Implement core GoalContextManager class with:
- `get_plan_context(limit)` - XML blocks for Plan phase (same-thread filter)
- `get_execute_briefing(limit)` - Markdown briefing for Execute phase (thread switch only)
- Extraction methods: `_extract_key_findings`, `_extract_critical_files`, `_extract_result_summary`

**Validation**: Unit tests for each method, filtering logic, extraction heuristics.

### Step 2: Modify Checkpoint Schema

**File**: `checkpoint.py`

Add thread_switch_pending field:
```python
thread_switch_pending: bool = False
"""Flag indicating thread just switched, Execute phase needs goal briefing."""
```

**Validation**: Schema validation tests, backward compatibility check.

### Step 3: Update State Manager

**File**: `state_manager.py`

Modify execute_thread_switch() to set flag:
```python
def execute_thread_switch(self, new_thread_id: str) -> None:
    # ... existing logic ...
    checkpoint.thread_switch_pending = True  # NEW
    # ... save ...
```

**Validation**: Thread switch integration tests, flag lifecycle tests.

### Step 4: Integrate into AgentLoop

**File**: `agent_loop.py`

Modify run_with_progress():
1. Create GoalContextManager instance
2. Call get_plan_context() at initialization
3. Inject into LoopState.plan_conversation_excerpts

```python
goal_context_manager = GoalContextManager(state_manager, config.goal_context)
plan_goal_excerpts = goal_context_manager.get_plan_context()
state = LoopState(plan_conversation_excerpts=plan_goal_excerpts + step_outputs, ...)
```

**Validation**: Integration tests, same-thread continuation tests.

### Step 5: Integrate into Executor

**File**: `executor.py`

Modify execute():
1. Create GoalContextManager instance (or receive from AgentLoop)
2. Call get_execute_briefing() per step
3. Inject into CoreAgent config.configurable.soothe_goal_briefing

```python
goal_briefing = goal_context_manager.get_execute_briefing()
config = {"configurable": {"soothe_goal_briefing": goal_briefing, ...}}
```

**Validation**: Thread switch recovery tests, CoreAgent briefing injection tests.

### Step 6: Add Configuration Schema

**File**: `config/models.py`

Add GoalContextConfig:
```python
class GoalContextConfig(BaseModel):
    plan_limit: int = Field(default=10, ge=1, le=50)
    execute_limit: int = Field(default=10, ge=1, le=50)
    enabled: bool = Field(default=True)

class AgenticConfig(BaseModel):
    goal_context: GoalContextConfig = Field(default_factory=GoalContextConfig)
```

**Files**: `config.yml`, `config.dev.yml`

Add goal_context section:
```yaml
agentic:
  goal_context:
    plan_limit: 10
    execute_limit: 10
    enabled: true
```

**Validation**: Config loading tests, default validation.

### Step 7: Create Unit Tests

**File**: `test_goal_context_manager.py`

Test suite:
- Plan context filtering (same-thread, completed only)
- Execute briefing flag behavior
- Cross-thread scope for Execute
- Extraction methods (bullet points, files, results)
- Error handling (checkpoint corruption, missing data)

### Step 8: Create Integration Tests

**File**: `test_goal_context_integration.py`

Integration test suite:
- Plan phase receives goal context
- Execute phase injects briefing on thread switch
- Execute phase skips briefing on same thread
- Full thread switch flow (flag lifecycle)

## Validation Checklist

### Implementation Validation

- [ ] GoalContextManager module created with all methods
- [ ] Checkpoint schema updated (thread_switch_pending field)
- [ ] State manager sets flag on thread switch
- [ ] AgentLoop injects goal context into LoopState
- [ ] Executor injects briefing into CoreAgent config
- [ ] Config schema extended (GoalContextConfig)
- [ ] Config files updated (config.yml, config.dev.yml)

### Unit Tests

- [ ] Plan context filters same-thread only
- [ ] Plan context filters completed goals only
- [ ] Plan context respects limit
- [ ] Execute briefing returns None without flag
- [ ] Execute briefing clears flag
- [ ] Execute briefing includes cross-thread goals
- [ ] Extraction methods tested (findings, files, results)
- [ ] Error handling tested (graceful degradation)

### Integration Tests

- [ ] Plan phase receives goal context
- [ ] Execute briefing injected on thread switch
- [ ] Execute briefing skipped on same thread
- [ ] Flag lifecycle (set → cleared)
- [ ] Same-thread continuation works
- [ ] Thread switch recovery works

### Functional Validation

- [ ] Run `./scripts/verify_finally.sh` (format, lint, tests)
- [ ] Manual test: "analyze performance" → "translate to chinese"
- [ ] Manual test: Thread switch scenario (RFC-608 triggers)
- [ ] Verify no breaking changes (backward compatibility)

## Implementation Notes

### Key Design Decisions

1. **Separate manager module**: Follows CoreAgent pattern (context management isolated from orchestration)
2. **Flag-based thread switch**: Simple, reliable mechanism (no complex detection logic)
3. **Different formats**: Plan needs full reports, Execute needs condensed summaries
4. **Same-thread vs cross-thread**: Plan local scope, Execute global scope for knowledge transfer

### Error Handling Strategy

All methods fail gracefully:
- Checkpoint errors → return empty context, log warning
- Extraction failures → use fallbacks (truncate, default text)
- No impact on execution flow if goal context unavailable

### Performance Considerations

- Plan context generated once at initialization (not per iteration)
- Execute briefing only generated when flag=True (early return)
- Simple regex extraction (no caching, results discarded after use)
- Configurable limits prevent unbounded growth

## Testing Approach

### Test Coverage Goals

- Unit tests: 95%+ coverage on GoalContextManager methods
- Integration tests: 80%+ coverage on AgentLoop integration points
- Edge cases: Empty history, flag stuck, config disabled, checkpoint corruption

### Test Scenarios

1. **First goal**: Empty history, no context injected
2. **Second goal same thread**: Goal1 injected into Plan, Execute skipped
3. **Thread switch**: Flag=True → Execute briefing generated, cleared
4. **Multiple goals**: Plan context respects limit=10
5. **Extraction edge cases**: No bullet points, no file paths, long reports

## Migration and Rollback

### Migration Path

No migration needed - pure additive feature:
- Existing checkpoints: thread_switch_pending defaults to False (safe)
- Existing config: goal_context defaults to enabled=true, limits=10 (safe)
- Existing behavior: preserved when goal_history empty or flag=False

### Rollback Plan

If issues arise:
1. Set goal_context.enabled=False in config (disable feature)
2. Remove GoalContextManager instantiation (code rollback)
3. Remove thread_switch_pending from checkpoint (schema rollback, optional)

No data migration, no breaking changes - safe to enable/disable at any time.

## Success Metrics

### Functional Metrics

- [ ] Same-thread continuation works (analyze → translate)
- [ ] Thread switch recovery works (knowledge transfer successful)
- [ ] No duplication (Execute briefing only on thread switch)
- [ ] Backward compatible (existing behavior unchanged)

### Quality Metrics

- [ ] All unit tests pass (95%+ coverage)
- [ ] All integration tests pass (80%+ coverage)
- [ ] Format check passes (ruff format)
- [ ] Lint check passes (ruff check, zero errors)
- [ ] No regressions in existing tests (900+ tests still pass)

## References

- RFC-609: Goal Context Management specification
- Design draft: docs/drafts/2026-04-17-goal-context-management-design.md
- RFC-608: Multi-Thread Lifecycle (thread_switch_pending integration)
- RFC-200: Agentic Goal Execution (AgentLoop integration)
- CoreAgent briefing pattern (soothe_goal_briefing mechanism)