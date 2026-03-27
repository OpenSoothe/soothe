# IG-077: Parallel Tool Execution Control Implementation

## Overview

**Purpose**: Enable functional parallel tool execution control with configurable limits.

**Status**: Planned

**Dependencies**: None

**Timeline**: ~5 hours

## Problem Analysis

### Current State

Investigation revealed:
- `ParallelToolsMiddleware` is placeholder (returns graph unchanged)
- `ParallelToolExecutor` implemented but never called
- `max_parallel_tools` config exists but has no effect
- LangGraph ToolNode executes with **unlimited parallelism** via `asyncio.gather()`

### Root Cause

Integration gap between Soothe components and LangGraph's ToolNode. All tool calls from single LLM response launch simultaneously with no concurrency control.

### Discovery

LangGraph already provides interception point: middleware `awrap_tool_call` hook called for each tool during parallel batch execution. Adding semaphore here naturally limits concurrency.

## Solution Architecture

### Approach: Middleware Hook + Semaphore

**Integration flow**:
```
Configuration (max_parallel_tools=10)
         ↓
ParallelToolsMiddleware.__init__(semaphore=asyncio.Semaphore(10))
         ↓
Agent factory adds middleware to stack
         ↓
LangGraph ToolNode launches N tools via asyncio.gather()
         ↓
Each tool calls middleware.awrap_tool_call(request, handler)
         ↓
async with semaphore:  ← LIMIT APPLIED HERE
    await handler(request)
         ↓
Only 10 tools execute concurrently, others wait for slot
```

### Advantages

1. Zero thirdparty modifications
2. Uses existing middleware hook mechanism
3. Minimal code (~50 lines)
4. Works for all tools (sync/async)
5. Natural async semaphore control

## Implementation Phases

### Phase 1: Configuration Update

**File**: `src/soothe/protocols/concurrency.py`

Change default `max_parallel_tools` to 10:
```python
max_parallel_tools: int = Field(
    default=10,
    description="Maximum tool calls running simultaneously. "
    "Set to 1 for sequential execution, 3-5 for conservative parallelism, "
    "10 for balanced API usage, 20+ for high-limit APIs. "
    "LangGraph default is unlimited; this provides sensible default.",
)
```

**Rationale**: 10 is balanced default for most APIs.

### Phase 2: Middleware Implementation

**File**: `src/soothe/middleware/parallel_tools.py`

1. Remove placeholder `modify_graph()` method (lines 44-64)
2. Remove unused factory `create_parallel_tool_executor()` (lines 71-91)
3. Add `__init__(max_parallel_tools: int)` with semaphore
4. Implement `awrap_tool_call(request, handler)`:
   ```python
   async def awrap_tool_call(self, request, handler):
       async with self._semaphore:
           logger.debug("Tool %s: executing", request.tool_call["name"])
           return await handler(request)
   ```
5. Add logging for observability

### Phase 3: Remove Obsolete Code

**Delete**: `src/soothe/core/parallel_tool_node.py` (177 lines)
- `ParallelToolExecutor` class now obsolete
- Similar logic now in middleware
- Never called in existing codebase

**Update**: `src/soothe/core/concurrency.py`
- Keep `acquire_tool()` for future hierarchical control
- Update docstring to clarify it's reserved

### Phase 4: Event System Integration

**File**: `src/soothe/middleware/parallel_tools.py`

Add events for observability:
```python
class ParallelToolSlotAcquired(SootheEvent):
    type: str = "soothe.parallel_tools.slot_acquired"
    tool_name: str
    active_count: int
    max_parallel: int

class ParallelToolSlotReleased(SootheEvent):
    type: str = "soothe.parallel_tools.slot_released"
    tool_name: str
    active_count: int
```

Register and emit events in middleware.

### Phase 5: Unit Tests

**File**: `tests/unit/middleware/test_parallel_tools.py` (NEW)

Test semaphore control:
- 5 tools, max_parallel=2, each 2s → expect ~5s total (batching proof)
- max_parallel=1 → expect ~10s (sequential proof)
- Error handling → semaphore released on exception
- Concurrent state updates

### Phase 6: Integration Tests

**File**: `tests/integration/test_parallel_tools_integration.py` (NEW)

Test with real agent:
- Config propagation validation
- Mixed sync/async tools
- Performance measurement vs sequential

### Phase 7: Verification

1. Run `./scripts/verify_finally.sh`
2. Manual verification with debug logs
3. Test extreme cases (max_parallel=1, max_parallel=20)

## File Changes Summary

| File | Action | Lines |
|------|--------|-------|
| `src/soothe/protocols/concurrency.py` | Update default | 32: 3→10 |
| `src/soothe/middleware/parallel_tools.py` | Implement + remove factory | 44-91 → awrap_tool_call |
| `src/soothe/core/parallel_tool_node.py` | DELETE | All 177 lines |
| `src/soothe/core/concurrency.py` | Update docstring | 81-91 |
| `tests/unit/middleware/test_parallel_tools.py` | CREATE | N/A |
| `tests/integration/test_parallel_tools_integration.py` | CREATE | N/A |

## Verification Criteria

### Must Pass

- [ ] All linting errors zero
- [ ] All 900+ unit tests pass
- [ ] Integration tests pass
- [ ] Semaphore limits verified via timing tests
- [ ] Error handling verified (semaphore released)

### Should Verify

- [ ] Debug logs show slot acquisition/release
- [ ] max_parallel=1 produces sequential execution
- [ ] max_parallel=10 allows meaningful parallelism
- [ ] Events emitted for observability

## Success Metrics

- Default 10 parallel tools providing balanced performance
- Unlimited parallelism now controlled with semaphore
- Obsolete code removed (177 lines deleted)
- Zero thirdparty modifications
- Full test coverage

## Alternative Approaches Considered

### Alternative A: Tool Wrapping
Rejected: Requires modifying tool registration, harder to access config.

### Alternative B: Replace ToolNode
Rejected: Too invasive, requires graph decompilation, fragile.

### Alternative C: Request deepagents Integration
Rejected: External dependency timing, can't implement now.

**Chosen**: Middleware hook + semaphore - cleanest, uses existing patterns.

## References

- RFC-0009: DAG-based Execution
- Investigation: LangGraph ToolNode implementation
- LangChain middleware patterns: ToolRetryMiddleware, FilesystemMiddleware
- Plan file: `/Users/chenxm/.claude/plans/cryptic-orbiting-kazoo.md`

## Next Steps

1. Update configuration default to 10
2. Implement middleware `awrap_tool_call`
3. Remove obsolete code
4. Add tests
5. Verify with `./scripts/verify_finally.sh`
6. Manual verification

---

**Implementation Lead**: Claude
**Date**: 2026-03-28
**Estimated Completion**: Same day (~5 hours)