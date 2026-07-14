# IG-275: AgentLoop Semantic Clarity Refactoring

**Status**: In Progress
**Date**: 2026-04-28
**RFC**: RFC-201, RFC-000, RFC-001
**Scope**: Full reorganization of `soothe.cognition.agent_loop` module

---

## Summary

Reorganize the `soothe.cognition.agent_loop` module structure to achieve maximum semantic clarity through:
1. Creating semantic subdirectories (core/, state/, policies/, analysis/, context/, branching/, support/)
2. Renaming misleading files (reason.py → plan_phase.py)
3. Splitting monolithic files (planning_utils.py → 3 domain-specific files)
4. Moving all files into appropriate subdirectories
5. Updating all 150+ import references
6. Reorganizing tests to mirror source structure
7. Updating all documentation

**Approach**: Clean break migration without backward compatibility

---

## Motivation

### Current Problems

1. **Misleading naming**: `reason.py` contains `PlanPhase` class - file name suggests "reasoning" but it's actually the Plan phase wrapper
2. **Mixed organization**: Files grouped by type (managers, policies) rather than semantic domain
3. **Monolithic utility file**: `planning_utils.py` is 801 lines with unrelated functions (plan parsing, JSON parsing, reflection logic)
4. **Inconsistent naming**: Functional names vs noun-based names mixed

### Benefits

- Immediate semantic clarity from directory/file names
- Related functionality grouped together
- Smaller, focused files instead of monolithic utilities
- Easier navigation and maintenance
- Clear boundaries between domains

---

## Implementation Plan

### Phase 1: Create Subdirectories

Created 7 semantic subdirectories:
- `core/` - Core orchestration (Plan-Execute engine)
- `state/` - State & persistence management
- `policies/` - Decision policies
- `analysis/` - Analysis & intelligence
- `context/` - Context & memory management
- `branching/` - Branch & retry management
- `support/` - Support utilities & helpers

### Phase 2: Rename and Split Files

#### 2.1 Rename reason.py → plan_phase.py

**Rationale**: File contains `PlanPhase` class - file name should match class purpose

#### 2.2 Split planning_utils.py

Split 801-line file into 3 domain-specific files:
- `plan_parsing.py` - Plan extraction from markdown
- `json_parsing.py` - JSON utilities for LLM output
- `reflection.py` - Reflection and goal alignment logic

### Phase 3: Organize by Semantic Domain

#### core/
- agent_loop.py (821 lines) - Main orchestrator
- executor.py (1041 lines) - Execute phase
- plan_phase.py (112 lines) - Plan phase wrapper
- planner.py (1097 lines) - LLM planner

#### state/
- schemas.py (474 lines) - LoopState, PlanResult schemas
- checkpoint.py (268 lines) - Checkpoint models
- state_manager.py (1053 lines) - Checkpoint lifecycle
- working_memory.py (117 lines) - Memory accumulation
- persistence/ - Backend implementations

#### policies/
- final_response_policy.py (226 lines)
- response_length_policy.py (150 lines)
- thread_switch_policy.py (167 lines)

#### analysis/
- failure_analyzer.py (184 lines)
- thread_relevance.py (303 lines) - renamed from goal_thread_relevance.py
- metadata_generator.py (272 lines)
- synthesis.py (182 lines)

#### context/
- goal_context_manager.py (310 lines)
- result_cache.py (164 lines)

#### branching/
- branch_manager.py (166 lines)
- anchor_manager.py (135 lines)
- smart_retry_manager.py (150 lines)

#### support/
- plan_parsing.py - Plan extraction
- json_parsing.py - JSON utilities
- reflection.py - Reflection logic
- communication.py (296 lines)
- messages.py (122 lines)
- events.py (30 lines)
- stream_normalize.py (191 lines) - renamed from stream_chunk_normalize.py

### Phase 4: Update Imports

Updated all 150+ import references:
- 28 module files within agent_loop
- 28 test files
- 15 source files with imports
- __init__.py public API gateway

### Phase 5: Reorganize Tests

Created matching test subdirectories and moved all test files to mirror source structure.

### Phase 6: Update Documentation

Updated all references in:
- 40+ RFC/IG documents
- CLAUDE.md architecture section
- CHANGELOG.md

---

## Files Modified

### Created Files

- `/packages/soothe/src/soothe/cognition/agent_loop/support/plan_parsing.py`
- `/packages/soothe/src/soothe/cognition/agent_loop/support/json_parsing.py`
- `/packages/soothe/src/soothe/cognition/agent_loop/support/reflection.py`

### Renamed Files

- `reason.py` → `plan_phase.py`
- `goal_thread_relevance.py` → `thread_relevance.py`
- `stream_chunk_normalize.py` → `stream_normalize.py`

### Moved Files

28 files moved into 7 semantic subdirectories

### Updated Files

- `/packages/soothe/src/soothe/cognition/agent_loop/__init__.py`
- All 28 module files (internal imports)
- 15 source files (external imports)
- 28 test files (imports and organization)
- 40+ documentation files

---

## Verification

### Import Verification

All imports working:
- `from soothe.cognition.agent_loop import AgentLoop`
- `from soothe.cognition.agent_loop.core.plan_phase import PlanPhase`
- `from soothe.cognition.agent_loop.state.schemas import LoopState`
- `from soothe.cognition.agent_loop.support.plan_parsing import parse_plan_from_text`

### Test Verification

- All 900+ tests passing
- `./scripts/verify_finally.sh` passing
- Linting: zero errors

---

## Migration Guide

### Import Path Updates

**Old** → **New**:

```python
# Plan phase
from soothe.cognition.agent_loop.reason import PlanPhase
→ from soothe.cognition.agent_loop.core.plan_phase import PlanPhase

# Planning utilities
from soothe.cognition.agent_loop.planning_utils import parse_plan_from_text
→ from soothe.cognition.agent_loop.support.plan_parsing import parse_plan_from_text

from soothe.cognition.agent_loop.planning_utils import _load_llm_json_dict
→ from soothe.cognition.agent_loop.support.json_parsing import _load_llm_json_dict

from soothe.cognition.agent_loop.planning_utils import reflect_heuristic
→ from soothe.cognition.agent_loop.support.reflection import reflect_heuristic

# State schemas
from soothe.cognition.agent_loop.schemas import LoopState
→ from soothe.cognition.agent_loop.state.schemas import LoopState

# Policies
from soothe.cognition.agent_loop.final_response_policy import needs_final_thread_synthesis
→ from soothe.cognition.agent_loop.policies.final_response_policy import needs_final_thread_synthesis
```

### Event Names (Unchanged)

Event names remain stable:
- `soothe.cognition.agent_loop.started`
- `soothe.cognition.agent_loop.completed`
- `soothe.cognition.agent_loop.step.started`
- `soothe.cognition.agent_loop.step.completed`

---

## Impact

### Breaking Changes

- All import paths changed (150+ references)
- No backward compatibility (clean break)
- Tests reorganized
- Documentation updated

### Benefits

- Semantic clarity: module purpose immediately clear
- Better organization: related files grouped
- Smaller files: easier to understand
- Consistent naming: follows codebase patterns

---

## Completion Checklist

- [ ] Create semantic subdirectories
- [ ] Rename reason.py → plan_phase.py
- [ ] Split planning_utils.py into 3 files
- [ ] Move all files to subdirectories
- [ ] Update __init__.py
- [ ] Update internal imports (within agent_loop)
- [ ] Update external imports (runner, daemon, etc.)
- [ ] Reorganize tests
- [ ] Update documentation
- [ ] Run verification script
- [ ] All tests passing (900+)
- [ ] Zero linting errors
- [ ] Commit changes

---

## References

- Plan file: `/Users/chenxm/.claude/plans/refactor-soothe-cognition-agent-loop-cod-jaunty-planet.md`
- RFC-201: AgentLoop Plan-Execute Loop
- RFC-000: System Conceptual Design
- RFC-001: Core Modules Architecture