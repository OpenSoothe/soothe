# IG-081: RFC-0001 Compliance Fixes

**Implementation Guide**: IG-081
**Title**: RFC-0001 Compliance Fixes and Updates
**Status**: Draft
**Created**: 2026-03-28
**Dependencies**: RFC-0001, RFC-0002, IG-036 (planner simplification), IG-047 (module refactoring)
**Related RFCs**: RFC-0001 (System Conceptual Design)

---

## Overview

This implementation guide addresses gaps discovered during systematic analysis of RFC-0001 against the current codebase implementation. The analysis verified all 6 core protocols and identified 4 issues requiring fixes.

## Scope

**In Scope**:
- Update RFC-0001 planner tier naming to reflect architectural evolution
- Document remote agent wrapping as future work
- Implement MCP session lifecycle management per-thread (Invariant 11)
- Implement context persistence on thread suspend/archive (Invariant 12)

**Out of Scope**:
- Remote agent wrapping implementation (deferred to future work when ACP/A2A are added)
- Other RFC compliance issues (each RFC analyzed separately in subsequent tasks)

---

## Findings Summary

### ✅ Verified: Core Protocols

All 6 core protocols from RFC-0001 are implemented with proper `Protocol` definitions:

| Protocol | Location | Status |
|----------|----------|--------|
| ContextProtocol | `protocols/context.py` | ✅ Implemented |
| MemoryProtocol | `protocols/memory.py` | ✅ Implemented |
| PlannerProtocol | `protocols/planner.py` | ✅ Implemented |
| PolicyProtocol | `protocols/policy.py` | ✅ Implemented |
| DurabilityProtocol | `protocols/durability.py` | ✅ Implemented |
| RemoteAgentProtocol | `protocols/remote.py` | ✅ Implemented |

**Protocol-first design principle**: Verified - no langchain/langgraph/deepagents imports in protocol signatures.

**Orchestrator wiring**: Verified - `create_soothe_agent()` properly resolves and attaches all protocols.

### 🔍 System Invariants Status

| Invariant | Status | Notes |
|-----------|--------|-------|
| 1. Protocol-first design | ✅ Verified | Clean protocol signatures |
| 2. Unbounded context ledger | ✅ Verified | `KeywordContext._entries` is list, projections bounded |
| 3. Subagent scoped context | ✅ Verified | `SubagentContextMiddleware` calls `project_for_subagent()` |
| 4. Explicit memory population | ✅ Verified | `MemoryProtocol.remember()` requires explicit call |
| 5. Policy checks all actions | ✅ Verified | `SoothePolicyMiddleware` intercepts all tool calls |
| 6. Durable state | ⚠️ Partial | Needs production deployment verification |
| 7. Subset permissions | ✅ Verified | `narrow_for_child()` returns intersection |
| 8. Uniform remote interface | ⚠️ Gap | Remote agents NOT wrapped as CompiledSubAgent |
| 9. Optional planner | ✅ Verified | `resolve_planner()` always returns SimplePlanner |
| 10. Context vs history separation | ⚠️ Unclear | Needs verification of SummarizationMiddleware interaction |
| 11. MCP thread lifecycle | ❌ Gap | MCP sessions global, NOT per-thread |
| 12. Context survives suspend | ❌ Gap | Context persisted after query, NOT on suspend |
| 13. Swappable implementations | ✅ Verified | Resolver uses config, protocols swappable |

---

## Issues and Fixes

### Issue 1: Planner Tier Naming Evolution

**Problem**: RFC-0001 states "Two planner tiers: DirectPlanner and SubagentPlanner" but current code has:
- SimplePlanner (formerly DirectPlanner, renamed in IG-028)
- AutoPlanner (complexity router)
- ClaudePlanner (complex tasks)

IG-036 removed SubagentPlanner to simplify architecture.

**Root Cause**: RFC not updated after architectural evolution.

**Fix**: Update RFC-0001 to document current 3-tier reality.

**Files to Modify**:
- `docs/specs/RFC-0001-system-conceptual-design.md` (line 53)

**Changes**:
```markdown
# OLD:
6. **Plan-driven execution** -- Complex goals are decomposed into plans with steps.
   Two planner tiers: `DirectPlanner` (single LLM call for simple tasks) and
   `SubagentPlanner` (multi-turn reasoning for complex tasks).

# NEW:
6. **Plan-driven execution** -- Complex goals are decomposed into plans with steps.
   Three planner tiers: `SimplePlanner` (single LLM call for simple tasks),
   `AutoPlanner` (complexity router that delegates), and `ClaudePlanner`
   (multi-turn reasoning for complex tasks). Architectural evolution: IG-036
   removed SubagentPlanner indirection, routing directly from AutoPlanner.
```

**Why**: Accept legitimate architectural simplification documented in IG-036 and IG-028.

---

### Issue 2: Remote Agent Wrapping Deferred

**Problem**: RFC-0001 Invariant 8 states "Remote agents are indistinguishable from local subagents at the delegation interface" and specifies wrapping as `CompiledSubAgent`.

Current: `LangGraphRemoteAgent` implements `RemoteAgentProtocol` but is NOT wrapped.

**Root Cause**: Only one remote implementation (LangGraph) exists; ACP/A2A not yet implemented.

**Fix**: Document current deviation and preserve future intent.

**Files to Modify**:
- `docs/specs/RFC-0001-system-conceptual-design.md` (line 95, line 134)

**Changes**:
```markdown
# OLD (line 95):
Invokes a remote agent and returns results. Implementations for ACP, A2A, and
LangGraph RemoteGraph. Each is wrapped as a deepagents `CompiledSubAgent` for
uniform access via the `task` tool.

# NEW (line 95):
Invokes a remote agent and returns results. Implementations for ACP, A2A, and
LangGraph RemoteGraph. **Future**: Each will be wrapped as a deepagents
`CompiledSubAgent` for uniform access via the `task` tool. **Current**:
`LangGraphRemoteAgent` uses direct `RemoteAgentProtocol` access; wrapping will
be implemented when ACP/A2A backends are added.

# OLD (line 134 - Invariant 8):
8. Remote agents are indistinguishable from local subagents at the delegation interface.

# NEW (line 134 - Invariant 8):
8. Remote agents are indistinguishable from local subagents at the delegation interface.
   **Current deviation**: Remote agents accessed via direct protocol. **Planned**:
   wrap as `CompiledSubAgent` when ACP/A2A implementations added (preserves
   Guiding Principle #9: uniform delegation envelope).
```

**Why**: Maintain RFC vision while acknowledging pragmatic implementation stage. User confirmed: implement in future when ACP/A2A added.

---

### Issue 3: MCP Session Lifecycle Not Per-Thread

**Problem**: RFC-0001 Invariant 11 states "MCP session lifecycle is managed alongside thread lifecycle (created on thread start, cleaned up on suspend/archive)".

**Current Behavior**:
- `MCPSessionManager` exists with `cleanup()` method ✅
- `load_mcp_tools()` returns session manager ✅
- BUT `resolve_tools()` does NOT load MCP tools ❌
- MCP sessions are global (loaded at agent startup), NOT per-thread ❌
- Thread lifecycle operations don't manage MCP sessions ❌

**Root Cause**: MCP integration added before thread lifecycle architecture finalized.

**Fix**: Implement per-thread MCP session management.

**Architecture**:

```python
# ThreadContextManager (src/soothe/core/thread/manager.py)
class ThreadContextManager:
    def __init__(self, durability, config):
        self._durability = durability
        self._config = config
        self._mcp_managers: dict[str, MCPSessionManager] = {}  # thread_id -> manager

    async def create_thread(self, metadata, thread_id):
        # ... existing code ...

        # Load MCP tools for this thread
        from soothe.mcp.loader import load_mcp_tools
        if self._config.mcp_servers:
            tools, mcp_manager = await load_mcp_tools(self._config.mcp_servers)
            self._mcp_managers[thread_info.thread_id] = mcp_manager
            # Store tools reference for this thread

        return thread_info

    async def suspend_thread(self, thread_id):
        # Persist context before suspending
        if self._context:
            await self._context.persist(thread_id)

        # Cleanup MCP sessions for this thread
        if thread_id in self._mcp_managers:
            await self._mcp_managers[thread_id].cleanup()
            del self._mcp_managers[thread_id]

        await self._durability.suspend_thread(thread_id)

    async def archive_thread(self, thread_id):
        # Persist context before archiving
        if self._context:
            await self._context.persist(thread_id)

        # Cleanup MCP sessions for this thread
        if thread_id in self._mcp_managers:
            await self._mcp_managers[thread_id].cleanup()
            del self._mcp_managers[thread_id]

        await self._durability.archive_thread(thread_id)
```

**Files to Modify**:
- `src/soothe/core/thread/manager.py` - Add MCP session management
- `src/soothe/core/runner/_runner_phases.py` - Remove global MCP tool loading
- `src/soothe/core/resolver/_resolver_tools.py` - Remove MCP from tool resolution

**Implementation Steps**:

1. Add `_mcp_managers: dict[str, MCPSessionManager]` to `ThreadContextManager`
2. Add `ContextProtocol` parameter to `ThreadContextManager.__init__`
3. Modify `create_thread()` to load MCP tools per-thread
4. Modify `suspend_thread()` to cleanup MCP + persist context
5. Modify `archive_thread()` to cleanup MCP + persist context
6. Update `SootheRunner` to pass context to `ThreadContextManager`
7. Remove global MCP loading from resolver

**Trade-offs**:
- **Pro**: Complete RFC compliance, proper resource cleanup, thread isolation
- **Con**: Slower thread startup (MCP load per-thread), more memory per-thread

**Why**: User selected option A - full implementation to match RFC intent.

---

### Issue 4: Context Not Persisted on Thread Suspend

**Problem**: RFC-0001 Invariant 12 states "Plan state and context ledger survive thread suspend/resume via DurabilityProtocol".

**Current Behavior**:
- `context.restore()` called in `_pre_stream()` when thread_id exists ✅
- `context.persist()` called in `_post_stream()` after query completes ✅
- BUT `suspend_thread()` in daemon doesn't call `context.persist()` ❌
- Inactivity timeout suspends threads without persisting context ❌

**Root Cause**: Context persistence only implemented in query execution flow, not thread lifecycle.

**Fix**: Add context persistence to thread suspend/archive operations.

**Files to Modify**:
- `src/soothe/core/thread/manager.py` (same as Issue 3)

**Implementation** (integrated with Issue 3):
```python
async def suspend_thread(self, thread_id):
    # Persist context before suspending
    if self._context:
        try:
            await self._context.persist(thread_id)
            logger.info("Context persisted before suspend for thread %s", thread_id)
        except Exception:
            logger.warning("Context persist failed for thread %s", thread_id, exc_info=True)

    # Cleanup MCP sessions (Issue 3)
    # ... existing code ...

async def archive_thread(self, thread_id):
    # Persist context before archiving
    if self._context:
        try:
            await self._context.persist(thread_id)
            logger.info("Context persisted before archive for thread %s", thread_id)
        except Exception:
            logger.warning("Context persist failed for thread %s", thread_id, exc_info=True)

    # Cleanup MCP sessions (Issue 3)
    # ... existing code ...
```

**Why**: User selected option A - complete implementation for crash recovery safety.

---

## Implementation Plan

### Phase 1: RFC Documentation Updates

**Files**: `docs/specs/RFC-0001-system-conceptual-design.md`

**Changes**:
1. Line 53: Update planner tier naming (Issue 1)
2. Line 95: Document remote agent wrapping future work (Issue 2)
3. Line 134: Update Invariant 8 with current deviation note (Issue 2)

**Verification**: Review RFC changes match design intent.

### Phase 2: Thread Lifecycle MCP Integration

**Files**:
- `src/soothe/core/thread/manager.py`
- `src/soothe/core/runner/__init__.py`
- `src/soothe/core/resolver/_resolver_tools.py`

**Changes**:
1. Add MCP session manager dict to `ThreadContextManager`
2. Add `ContextProtocol` parameter to `ThreadContextManager.__init__`
3. Load MCP tools in `create_thread()` (Issue 3)
4. Cleanup MCP in `suspend_thread()` (Issue 3)
5. Cleanup MCP in `archive_thread()` (Issue 3)
6. Persist context in `suspend_thread()` (Issue 4)
7. Persist context in `archive_thread()` (Issue 4)
8. Pass context from `SootheRunner` to `ThreadContextManager`
9. Remove global MCP loading from resolver

**Verification**:
- Unit tests for MCP lifecycle per-thread
- Integration tests for context persistence on suspend
- Verify inactivity timeout triggers context persist

### Phase 3: Testing and Validation

**Tests**:
- `tests/unit/test_thread_manager.py` - MCP lifecycle per-thread
- `tests/unit/test_context.py` - Context persist/restore on suspend
- `tests/integration/test_daemon_lifecycle.py` - Daemon inactivity timeout

**Verification Script**:
```bash
./scripts/verify_finally.sh
```

---

## Success Criteria

1. ✅ RFC-0001 updated with planner tier evolution
2. ✅ RFC-0001 documents remote agent future intent
3. ✅ MCP sessions created per-thread, cleaned up on suspend/archive
4. ✅ Context persisted before suspend/archive
5. ✅ All unit tests pass
6. ✅ Integration tests pass
7. ✅ `./scripts/verify_finally.sh` passes (format + lint + tests)

---

## Risk Assessment

**Low Risk**:
- RFC documentation updates (Issue 1, 2) - no code changes

**Medium Risk**:
- MCP per-thread loading - performance impact on thread startup
- Context persistence on suspend - additional I/O during lifecycle

**Mitigation**:
- Benchmark thread startup time with MCP tools
- Profile context persistence overhead during suspend
- Consider lazy MCP loading if startup time degrades

---

## References

- RFC-0001: System Conceptual Design
- RFC-0002: Core Modules Architecture
- IG-028: Direct-to-Simple-Planner Renaming
- IG-036: Planning Workflow Refactoring (removed SubagentPlanner)
- IG-047: Module Self-Containment Refactoring