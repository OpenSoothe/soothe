# IG-486: AgentLoop → StrangeLoop Migration Summary

## Overview

This migration renamed the core orchestration class from `AgentLoop` to `StrangeLoop` (with short alias `Sloop`) across the entire Soothe codebase. The migration was motivated by:

1. **Terminology clarity**: "StrangeLoop" better reflects the recursive, self-referential nature of the Plan-Execute-Judge pattern (inspired by Douglas Hofstadter's concept)
2. **Namespace consistency**: Aligns with `StrangeLoopStateManager`, `StrangeLoopCheckpoint`, and event namespace `soothe.cognition.strange_loop.*`
3. **Branding**: Distinguishes Soothe's core loop from generic "agent loop" terminology

## Migration Scope

### Core Files Renamed

| Old Path | New Path | Notes |
|----------|----------|-------|
| `packages/soothe/src/soothe/foundation/loop/engine/agent_loop.py` | `packages/soothe/src/soothe/foundation/loop/engine/strange_loop.py` | Main orchestration class |
| `packages/soothe/src/soothe/foundation/loop/state/manager.py` | `packages/soothe/src/soothe/foundation/loop/state/sloop_manager.py` | State manager renamed |
| `packages/soothe/src/soothe/protocols/agent_loop.py` | `packages/soothe/src/soothe/protocols/strange_loop.py` | Protocol definition |

### Classes Renamed

| Old Class | New Class | Backward Compatibility Alias |
|-----------|-----------|------------------------------|
| `AgentLoop` | `StrangeLoop` | `AgentLoop = StrangeLoop` (via `__getattr__`) |
| `AgentLoopStateManager` | `StrangeLoopStateManager` | `AgentLoopStateManager = StrangeLoopStateManager` |
| `AgentLoopCheckpoint` | `StrangeLoopCheckpoint` | `AgentLoopCheckpoint = StrangeLoopCheckpoint` |
| `AgentLoopProtocol` | `StrangeLoopProtocol` | `AgentLoopProtocol = StrangeLoopProtocol` |

### Constants Renamed

| Old Constant | New Constant | Backward Compatibility Alias |
|--------------|--------------|------------------------------|
| `AGENT_LOOP_STARTED` | `STRANGE_LOOP_STARTED` | `AGENT_LOOP_STARTED = STRANGE_LOOP_STARTED` |
| `AGENT_LOOP_COMPLETED` | `STRANGE_LOOP_COMPLETED` | `AGENT_LOOP_COMPLETED = STRANGE_LOOP_COMPLETED` |
| `AGENT_LOOP_PLAN_DECISION` | `STRANGE_LOOP_PLAN_DECISION` | `AGENT_LOOP_PLAN_DECISION = STRANGE_LOOP_PLAN_DECISION` |
| `AGENT_LOOP_STEP_STARTED` | `STRANGE_LOOP_STEP_STARTED` | `AGENT_LOOP_STEP_STARTED = STRANGE_LOOP_STEP_STARTED` |
| `AGENT_LOOP_STEP_COMPLETED` | `STRANGE_LOOP_STEP_COMPLETED` | `AGENT_LOOP_STEP_COMPLETED = STRANGE_LOOP_STEP_COMPLETED` |
| `AGENT_LOOP_CONTEXT_COMPACTED` | `STRANGE_LOOP_CONTEXT_COMPACTED` | `AGENT_LOOP_CONTEXT_COMPACTED = STRANGE_LOOP_CONTEXT_COMPACTED` |

### Event Classes Renamed

| Old Event Class | New Event Class | Backward Compatibility Alias |
|-----------------|-----------------|------------------------------|
| `AgentLoopStartedEvent` | `StrangeLoopStartedEvent` | `AgentLoopStartedEvent = StrangeLoopStartedEvent` |
| `AgentLoopCompletedEvent` | `StrangeLoopCompletedEvent` | `AgentLoopCompletedEvent = StrangeLoopCompletedEvent` |
| `AgentLoopPlanDecisionEvent` | `StrangeLoopPlanDecisionEvent` | `AgentLoopPlanDecisionEvent = StrangeLoopPlanDecisionEvent` |
| `AgentLoopStepStartedEvent` | `StrangeLoopStepStartedEvent` | `AgentLoopStepStartedEvent = StrangeLoopStepStartedEvent` |
| `AgentLoopStepCompletedEvent` | `StrangeLoopStepCompletedEvent` | `AgentLoopStepCompletedEvent = StrangeLoopStepCompletedEvent` |

## Import Path Changes

### Public API (User-facing)

```python
# OLD
from soothe.foundation.loop import AgentLoop
from soothe.foundation.loop.engine.agent_loop import AgentLoop
from soothe.foundation.loop.state.manager import AgentLoopStateManager

# NEW (recommended)
from soothe.foundation.loop import StrangeLoop, Sloop
from soothe.foundation.loop.engine.strange_loop import StrangeLoop
from soothe.foundation.loop.state.sloop_manager import StrangeLoopStateManager

# BACKWARD COMPATIBLE (still works)
from soothe.foundation.loop import AgentLoop  # Returns StrangeLoop via __getattr__
```

### Internal Module Updates

All internal imports across `packages/soothe/src/soothe/` were updated:

```python
# Before
from soothe.foundation.loop.engine.agent_loop import AgentLoop
from soothe.foundation.loop.state.manager import AgentLoopStateManager
from soothe.protocols.agent_loop import AgentLoopProtocol

# After  
from soothe.foundation.loop.engine.strange_loop import StrangeLoop
from soothe.foundation.loop.state.sloop_manager import StrangeLoopStateManager
from soothe.protocols.strange_loop import StrangeLoopProtocol
```

## RuntimeContext Changes

The `LoopRuntimeContext` dataclass had a field renamed:

```python
# Before
@dataclass
class LoopRuntimeContext:
    agent_loop: AgentLoop  # Primary field
    ...

# After
@dataclass  
class LoopRuntimeContext:
    strange_loop: StrangeLoop  # Primary field
    ...
```

**Important**: A backward-compatible property was added to avoid breaking existing code:

```python
@property
def agent_loop(self) -> StrangeLoop:
    """Legacy alias for strange_loop."""
    return self.strange_loop
```

## Test Fix Patterns

Several test files needed updates due to mock patch path changes. The key pattern:

### Mock Patch Path Updates

```python
# OLD - patches at definition location (incorrect for mocking)
patch("soothe.foundation.loop.state.manager.AgentLoopStateManager", ...)
patch("soothe.foundation.loop.engine.agent_loop.CheckpointAnchorManager", ...)
patch("soothe.foundation.loop.engine.agent_loop.AgentLoopStateManager", ...)

# NEW - patches at usage location (correct for mocking)
patch("soothe.foundation.loop.engine.strange_loop.StrangeLoopStateManager", ...)
patch("soothe.foundation.loop.engine.strange_loop.CheckpointAnchorManager", ...)
patch("soothe.foundation.loop.state.sloop_manager.PersistenceDirectoryManager.get_loop_checkpoint_path", ...)
```

### Test Files Updated

| Test File | Fix Applied |
|-----------|-------------|
| `tests/unit/core/loop/core/test_agent_loop_adaptive_final.py` | Patch targets updated to `strange_loop` module |
| `tests/unit/core/loop/engine/test_agent_loop_clarification_policy.py` | Patch targets updated to `strange_loop` module |
| `tests/unit/core/loop/state/test_checkpoint_index_fix.py` | PersistenceDirectoryManager patch path fixed |
| `tests/unit/core/loop/state/test_clobbered_status_recovery.py` | PersistenceDirectoryManager patch path fixed |
| `tests/unit/core/loop/state/test_goal_record_enrichment.py` | PersistenceDirectoryManager patch path fixed |

## Bugs Fixed During Migration

### 1. Duplicate Property in LoopRuntimeContext

**Issue**: The `runtime_context.py` file had both a dataclass field `strange_loop` AND a property `strange_loop`, causing a `TypeError`:

```
TypeError: non-default argument 'state_manager' follows default argument
```

**Fix**: Removed the duplicate property definition (lines 70-73), keeping only the dataclass field.

### 2. Missing Event Exports

**Issue**: Tests importing `StrangeLoopPlanDecisionEvent` and other `StrangeLoop*` event classes failed because they weren't exported from `events/__init__.py`.

**Fix**: Added all StrangeLoop event classes to both the import and `__all__` list:
- `StrangeLoopStartedEvent`
- `StrangeLoopCompletedEvent`
- `StrangeLoopPlanDecisionEvent`
- `StrangeLoopStepStartedEvent`
- `StrangeLoopStepQueuedEvent`
- `StrangeLoopStepCompletedEvent`
- `StrangeLoopContextCompactionEvent`

## Verification Results

After all fixes, `./scripts/verify_finally.sh` passes:
- ✓ soothe-sdk unit tests passed
- ✓ soothe-cli unit tests passed  
- ✓ soothe unit tests passed
- ✓ soothe-daemon unit tests passed
- ✓ All lint checks passed
- ✓ All formatting checks passed
- ✓ Import boundary checks passed

## Remaining Work

### Phase 5: Documentation (TODO)
- RFCs still reference "AgentLoop" terminology
- IGs still reference "AgentLoop" terminology  
- User guide still references "AgentLoop" terminology
- Wiki documentation needs updates

### Phase 6: Scripts/Diagrams (TODO)
- `scripts/visualize_strange_loop_graph.py` still uses old naming
- `docs/diagrams/strange_loop_graph_nodes.md` still uses old naming

## Migration Commands Used

```bash
# Verify after fixes
./scripts/verify_finally.sh

# Check test failures
uv run pytest packages/soothe/tests/unit -v --tb=short

# Fix patch paths in tests
sed -i '' 's/soothe.foundation.loop.state.manager/soothe.foundation.loop.state.sloop_manager/g' <test_files>
```

## Key Lessons

1. **Mock patch paths must target usage location**: When a class is imported into a module (e.g., `StrangeLoopStateManager` imported into `strange_loop.py`), patches must target `soothe.foundation.loop.engine.strange_loop.StrangeLoopStateManager`, not the definition location.

2. **Dataclass fields vs properties**: A dataclass cannot have a property with the same name as a field - the property gets treated as a default value, breaking field ordering.

3. **Backward compatibility via `__getattr__`**: Using lazy imports with `__getattr__` allows old import paths to continue working while new paths are preferred.

4. **Export all variants**: When renaming classes that have both "Agentic" and "StrangeLoop" variants (aliases), ensure all are exported from `__init__.py` for test compatibility.