# RFC-209: Executor Thread Isolation Simplification

**RFC**: 209
**Title**: Layer 2 Executor Thread Isolation Simplification
**Status**: Draft
**Kind**: Architecture Refactoring
**Created**: 2026-04-09
**Updated**: 2026-04-09
**Dependencies**: RFC-201, RFC-100, RFC-001

## Abstract

This RFC simplifies the thread isolation implementation in Layer 2's executor by removing manual thread ID generation and leveraging langgraph's built-in concurrency handling. The current implementation creates isolated thread IDs (`{thread_id}__l2act{uuid}` and `{thread_id}__step_{i}`) and manually merges results back to the parent thread. This design removes ~80 lines of redundant code by trusting langgraph's atomic state management and the task tool's automatic subagent isolation.

## Motivation

### Current Problem

The executor in `src/soothe/cognition/agent_loop/executor.py` manually manages thread isolation:

1. **Manual Thread ID Generation**: Creates isolated thread IDs for subagent steps and parallel tool executions
2. **Manual Merge Logic**: `_merge_isolated_act_into_parent_thread()` combines isolated thread messages back to parent
3. **Mixed Strategy**: Different isolation strategies for subagent vs tool-only steps
4. **Documentation Confusion**: RFC-201 states "isolation is automatic" but implementation is manual

### Key Observation

langgraph's `task` tool already provides automatic thread isolation for subagent delegations. The manual thread management duplicates work langgraph handles internally.

### Root Cause Analysis

**What the original design tried to prevent**:
- Cross-wave contamination (research output interfering with translation)
- Concurrent execution conflicts (parallel steps racing on shared state)
- Context pollution (prior wave outputs affecting delegation reasoning)

**What langgraph already handles**:
- Atomic message queue operations (thread-safe state updates)
- AsyncSqliteSaver/AsyncPostgresSaver atomic state management
- task tool automatic isolated thread branches for subagents
- ToolMessage separation (each tool execution gets separate object)

**Insight**: Manual thread isolation solved problems langgraph already solves.

## Architecture Change

### Before (Verbose)

```
Layer 2 Executor:
├─ Detect step type (tool vs subagent)
├─ Create isolated thread_id: {parent}__l2act{uuid} or {parent}__step_{i}
├─ Pass thread_id to CoreAgent
├─ Execute on isolated branch
└─ Merge messages back to parent (manual)
```

### After (Simplified)

```
Layer 2 Executor:
├─ Pass parent thread_id to CoreAgent (no suffix)
├─ For tool steps: execute on parent thread (langgraph handles concurrency)
├─ For subagent steps: task tool creates isolated branch automatically
└─ Results flow back naturally (no manual merge)
```

### Separation of Concerns

**executor.py (Layer 2)**: Orchestration (what, when, how to sequence)
**CoreAgent (Layer 1)**: Thread mechanics (state management, execution)
**task tool**: Automatic subagent isolation

Executor should not manage thread IDs.

## Specification

### Code Changes

#### Methods to Remove

1. `_should_use_isolated_sequential_thread()` (lines 88-103 in executor.py)
   - Checks if sequential wave should use isolated thread
   - Removed: no longer needed

2. `_merge_isolated_act_into_parent_thread()` (lines 150-188)
   - Merges isolated branch messages to parent
   - Removed: no isolated threads created

#### Logic Simplification

3. `_execute_sequential_chunk()`: Remove isolated thread ID creation
   ```python
   # Always use parent thread_id
   act_thread_id = state.thread_id
   ```

4. `_execute_parallel()`: Remove step index suffix
   ```python
   # All parallel steps use parent thread_id
   tasks = [
       asyncio.create_task(
           self._execute_step_collecting_events(step, state.thread_id, state.workspace)
       )
       for step in steps
   ]
   ```

5. `_execute_step_collecting_events()`: Simplify signature (no isolated thread IDs)

#### State Management Changes

6. Remove `act_will_have_checkpoint_access` from LoopState (schemas.py)
   - Always True (same thread_id for all executions)

7. Remove `sequential_act_isolated_thread` from config

#### Reason Phase Simplification

8. `reason.py`: Remove checkpoint access conditional logic
   - Always inject prior conversation (same thread_id)

### Thread Safety Guarantees

**Concurrent Tool Execution**: langgraph's atomic state updates prevent conflicts
- AsyncSqliteSaver uses database transactions
- Message queue maintains FIFO ordering per thread
- Tools are independent function calls (no shared mutable state)
- ToolMessage separation prevents result mixing

**Subagent Isolation**: task tool already handles automatically
- Creates `{parent_thread_id}__task_{uuid}` internally
- Results merge back via ToolMessage
- executor just passes parent thread_id

**Context Contamination Prevention**:
- task tool isolates subagent executions
- ToolMessage stores results separately
- Sequential mode uses combined input (not prior history)
- State atomicity prevents interleaving

### Testing Requirements

1. **Parallel Tool Execution**: Test concurrent file operations on shared thread_id
2. **Sequential with Subagent**: Verify task tool isolation and ToolMessage return
3. **Dependency Mode**: Test concurrent waves with dependencies
4. **Performance**: Measure context tokens, latency, memory (expect improvement)

## Implementation Impact

### Benefits

**Code Simplification**:
- Remove ~80 lines of thread management code
- executor.py becomes pure orchestration logic
- Fewer conditional branches
- Easier maintenance

**Architectural Clarity**:
- Executor orchestrates, Layer 1 handles threads
- Consistent strategy (single thread_id for tools)
- Automatic isolation for subagents (task tool)

**Performance**:
- Reduced context tokens (no isolated thread history duplication)
- No merge overhead
- Lower memory footprint

**Documentation Alignment**:
- RFC-201 "automatic isolation" becomes accurate
- Implementation matches specification

### Risks

**Risk 1**: Concurrent tool conflicts
- Mitigation: langgraph designed for concurrent execution, atomic state updates
- Verification: Test parallel operations

**Risk 2**: Context contamination
- Mitigation: task tool already isolates, ToolMessage separation
- Verification: Test sequential mode with subagent + tool

**Risk 3**: Performance regression
- Mitigation: Actually improves (no duplication)
- Verification: Benchmark before/after

## Related Documents

- RFC-201: Layer 2 Agentic Goal Execution (main spec)
- RFC-100: Layer 1 CoreAgent Runtime
- RFC-001: Core Modules Architecture
- RFC-208: CoreAgent Message Optimization (similar simplification)
- Design Draft: `docs/drafts/2026-04-09-thread-isolation-simplification-design.md`

## Implementation Guide

Create IG-NNN for this refactoring:
- Phase 1: Remove thread isolation methods
- Phase 2: Simplify execution logic
- Phase 3: Remove state/config fields
- Phase 4: Update reason.py
- Phase 5: Run test suite (900+ tests)
- Phase 6: Performance benchmarks
- Phase 7: Update documentation

## Success Criteria

1. All existing tests pass (900+)
2. New concurrency tests pass
3. No performance regression (benchmark validates)
4. Context usage reduced (measured)
5. Code complexity reduced (~80 lines)
6. Documentation aligned

## Changelog

### 2026-04-09
- Initial draft RFC created
- Design based on approved draft from Platonic Brainstorming

---

**Status**: Draft - Pending `specs-refine` integration with RFC-201
**Next**: Run specs-refine to validate and integrate