# IG-295: Remove Dead Core Exports

## Summary

Remove 30+ unnecessary exports from soothe.core module public API to improve maintainability and reduce confusion for downstream users.

## Context

**Problem**: soothe.core module exports many functions/models via `__all__` that are never imported externally. Exploration revealed these "dead exports" are actually **active internal functions** imported directly from source files. The dead code is the **export mechanism itself**, not the implementation.

**Impact**:
- Reduces public API surface by 30+ exports
- Zero breaking changes (implementations remain functional)
- Improves code maintainability

**Discovery Method**: Three parallel exploration agents:
1. Module structure scan (120 files, 17 packages)
2. Usage grep across codebase (93 files importing from soothe.core)
3. Deprecation/compatibility pattern search

**Key Insight**: Removing exports from `__all__` is safe - functions remain available via direct imports from source modules.

---

## Phase 1: Dead Exports (Zero External Imports) - HIGH SAFETY

### 1.1 soothe.core.__init__.py

**Remove**: `INVALID_WORKSPACE_DIRS`
- Imported from soothe_sdk.utils but zero imports from soothe.core
- File: `packages/soothe/src/soothe/core/__init__.py`

### 1.2 workspace/__init__.py

**Remove 5 exports**:
- `strict_workspace_path` - only internal use
- `create_workspace_aware_backend` - zero imports
- `filesystem_virtual_mode_from_soothe_config` - zero imports
- `max_file_size_mb_for_filesystem_backend` - zero imports
- `resolve_backend_os_path` - only internal in security module

**File**: `packages/soothe/src/soothe/core/workspace/__init__.py`

### 1.3 thread/__init__.py

**Remove 5 exports**:
- `ThreadStats` - no imports
- `ThreadMessage` - no imports
- `EnhancedThreadInfo` - no imports
- `ExecutionContext` - no imports
- `ArtifactEntry` - duplicate (in persistence module)

**File**: `packages/soothe/src/soothe/core/thread/__init__.py`

### 1.4 scheduling/__init__.py

**Remove 2 exports**:
- `get_cache_stats` - zero imports
- `clear_tool_cache` - zero imports

**File**: `packages/soothe/src/soothe/core/scheduling/__init__.py`

### 1.5 prompts/__init__.py

**Remove 4 exports**:
- `RFC104_CONTEXT_XML_VERSION` - zero imports
- `build_shared_environment_workspace_prefix` - zero imports
- `build_soothe_protocols_section` - zero imports
- `build_soothe_thread_section` - zero imports

**File**: `packages/soothe/src/soothe/core/prompts/__init__.py`

---

## Phase 2: Internal-Only Exports (MEDIUM SAFETY)

### 2.1 goal_engine/__init__.py

**Remove 6 exports** (internal-only):
- `TERMINAL_STATES` - no imports
- `GoalSubDAGStatus` - no imports
- `BackoffDecision` - internal only
- `EvidenceBundle` - internal only
- `ContextConstructionOptions` - internal only
- `ThreadRelationshipModule` - 1 direct import in resolver

**File**: `packages/soothe/src/soothe/core/goal_engine/__init__.py`

### 2.2 agent_loop/__init__.py

**Remove 8 exports** (internal-only):
- `AgentLoopStateManager` - no imports
- `ActWaveRecord` - internal
- `AgentDecision` - internal
- `AgentLoopCheckpoint` - internal
- `ReasonStepRecord` - internal
- `StepExecutionRecord` - internal
- `WorkingMemoryState` - internal
- `GoalCommunicationHelper` - 1 test direct import

**Keep**: AgentLoop, LoopWorkingMemory, LoopState, PlanResult, StepAction, StepResult (used externally)

**File**: `packages/soothe/src/soothe/core/agent_loop/__init__.py`

### 2.3 runner/__init__.py

**Remove 3 exports**:
- `IterationRecord` - no imports outside runner internals
- `RunnerState` - 1 test direct import
- `StreamChunk` - duplicate (in events module)

**File**: `packages/soothe/src/soothe/core/runner/__init__.py`

---

## Implementation Steps

### Step 1: Create IG-295 (This Document)
Track all dead export removal work.

### Step 2: Remove Phase 1 Exports (HIGH SAFETY)
Edit 5 `__init__.py` files to remove dead exports from `__all__` lists.

### Step 3: Remove Phase 2 Exports (MEDIUM SAFETY)
Edit 3 `__init__.py` files to remove internal-only exports.

### Step 4: Run Verification
Execute `./scripts/verify_finally.sh` to ensure 900+ tests pass.

### Step 5: Commit Changes
Git commit with reference to IG-295.

---

## Verification

**Level 1**: Syntax check
```bash
python -m py_compile packages/soothe/src/soothe/core/__init__.py
python -c "from soothe.core import CoreAgent"  # Test remaining exports
```

**Level 2**: Full test suite
```bash
./scripts/verify_finally.sh
```

Expected: All 900+ tests pass, zero import errors.

---

## Expected Outcome

- **Total exports removed**: 30+ from 8 `__init__.py` files
- **Public API**: Cleaner, more maintainable
- **Internal code**: Unchanged, still functional via direct imports
- **Tests**: Pass unchanged

---

## Timeline

**Phase 1**: 1-2 days (HIGH SAFETY, quick wins)
**Phase 2**: 2-3 days (MEDIUM SAFETY, verify direct imports)
**Total**: 3-5 days

---

## References

- Plan: `/Users/xiamingchen/.claude/plans/woolly-greeting-iverson.md`
- RFC-000: System Conceptual Design
- IG-047: Module Self-Containment Refactoring

---

## Status

- [x] IG created
- [x] Phase 1 exports removed (17 items from 5 files)
- [x] Phase 2 exports removed (17 items from 3 files)
- [x] Verification passed (1490 tests)
- [x] Committed (6139ebee)

**Total exports removed**: 34 from 8 `__init__.py` files
**Test fixes**: 1 test import updated (RunnerState)
**Public API**: Cleaner, more maintainable