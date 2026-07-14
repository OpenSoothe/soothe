# IG-150: Planning Module Consolidation

**Status**: In Progress
**Started**: 2026-04-11
**RFC References**: RFC-604 (Plan Phase Robustness), RFC-0002 (Planner Protocol)
**Related IGs**: IG-036 (SubagentPlanner removal), IG-028 (Direct→Simple→LLMPlanner evolution)
**Updated**: 2026-04-12 (terminology refactoring per IG-153)

## Overview

Consolidate the planning module by removing redundant abstraction layers (ClaudePlanner, AutoPlanner) and merging the remaining LLMPlanner into the agent_loop module. This simplification reduces complexity while preserving all essential functionality.

## Goals

1. Remove ClaudePlanner (217-line thin wrapper around Claude subagent)
2. Remove AutoPlanner (147-line routing logic based on task complexity)
3. Use LLMPlanner as the unique planner implementation
4. Merge cognition.planning module into cognition.agent_loop module
5. Preserve query classification functionality (separate module)
6. Simplify config fields for planner selection

## Rationale

### Why Remove ClaudePlanner?
- 217-line thin wrapper that doesn't add essential value
- Claude subagent functionality still available via task tool in execution
- LLMPlanner handles all current use cases effectively

### Why Remove AutoPlanner?
- Pure routing layer adding indirection overhead
- Routing based on unified_classification.task_complexity
- LLMPlanner can handle all complexity levels directly
- Query classification handles chitchat separately (pre-planning)

### Why Merge into agent_loop?
- Planning and agent loop are tightly coupled
- Better cohesion: both implement Layer 2 ReAct loop
- Reduces module proliferation (5 files → 2 files)
- Total code: 2077 lines → 1705 lines (18% reduction)

## Current Architecture

```
cognition/planning/
  llm.py (1373 lines) - LLMPlanner implementation
  claude.py (217 lines) - ClaudePlanner wrapper
  router.py (147 lines) - AutoPlanner routing
  _shared.py (332 lines) - shared utilities
  __init__.py (8 lines)

core/resolver/
  __init__.py - resolve_planner() creates AutoPlanner routing to both

config/models.py
  PlannerProtocolConfig.routing: "auto" | "always_direct" | "always_planner" | "always_claude"
```

## Target Architecture

```
cognition/agent_loop/
  planner.py (1373 lines) - renamed from llm.py
  planning_utils.py (332 lines) - renamed from _shared.py
  agent_loop.py, reason.py, executor.py, schemas.py, etc. (unchanged)

core/resolver/
  __init__.py - resolve_planner() returns LLMPlanner directly

config/models.py
  PlannerProtocolConfig.model: "think" | "fast"
  PlannerProtocolConfig.use_fast_model: bool

Query classification (unchanged):
  core/unified_classifier.py - separate module, not modified
```

## Implementation Steps

### Phase 1: Move Utilities to _shared.py (Break Dependencies)

**Critical dependency**: ClaudePlanner imports utilities from llm.py. Must extract first.

**Actions**:
1. Move from llm.py to _shared.py:
   - `_default_agent_decision()` (lines 358-393)
   - `parse_reason_response_text()` (lines 644-728)
   - Constants: `_DEFAULT_DECISION_GOAL_SNIP_LEN`, `_LAYER2_GOAL_ALIGN_SNIP_LEN`
   - Helper: `_align_layer2_step_descriptions()` (lines 293-311)

2. Update imports:
   - llm.py imports from _shared.py
   - claude.py imports from _shared.py (temporary)
   - agent_loop.py imports from _shared.py (temporary)

**Verification**: `pytest tests/unit/test_planning.py tests/unit/test_shared_planning.py`

### Phase 2: Delete ClaudePlanner and AutoPlanner

**Actions**:
1. Delete files:
   - `/src/soothe/cognition/planning/claude.py`
   - `/src/soothe/cognition/planning/router.py`

2. Remove imports from resolver/__init__.py

3. Delete test file:
   - `/tests/unit/test_auto_planner.py`

**Verification**: `pytest tests/unit/test_planning.py`

### Phase 3: Simplify Resolver

**Actions**:
1. Remove ClaudePlanner creation logic (lines 129-146 in resolver/__init__.py)
2. Remove AutoPlanner creation (lines 151-160)
3. Remove routing config checks
4. Simplify to always return LLMPlanner instance

**Verification**: `pytest tests/unit/test_config.py tests/unit/test_core_agent.py`

### Phase 4: Simplify Config

**Actions**:
1. Add new config fields with backward compatibility:
   ```python
   model: str = "think"
   use_fast_model: bool = True
   # Deprecated fields kept for compatibility
   routing: Literal[...] = "auto"
   planner_model: str = "think"
   ```

2. Update resolver to use new fields
3. Update config.yml and config.dev.yml

**Verification**: Config parsing tests pass

### Phase 5: Merge Planning Module into Agent Loop

**Actions**:
1. Move files:
   - `llm.py` → `agent_loop/planner.py`
   - `_shared.py` → `agent_loop/planning_utils.py`

2. Update imports in moved files
3. Update imports throughout codebase:
   - resolver/__init__.py
   - agent_loop/agent_loop.py
   - All test files

4. Delete planning module directory

**Verification**: `pytest tests/unit/test_planning*.py tests/unit/test_reason*.py`

### Phase 6: Update Tests

**Actions**:
1. Delete test_auto_planner.py
2. Update imports in test files:
   - test_planning.py
   - test_shared_planning.py
   - test_planning_llm_json_parse.py
   - test_enhanced_reflection.py

3. Add tests for:
   - Simplified resolve_planner()
   - Config backward compatibility

**Verification**: `./scripts/verify_finally.sh`

### Phase 7: Documentation Updates

**Actions**:
1. Update RFC documents (RFC-0002, RFC-0008, RFC-0012)
2. Update module READMEs
3. Update PlannerProtocolConfig docstring

## Expected Outcomes

### Code Reduction
- Before: 2077 lines (5 files in planning module)
- After: 1705 lines (2 files in agent_loop module)
- Reduction: 372 lines (18%)

### Config Simplification
- Before: 4 routing options + planner_model field
- After: 2 fields (model, use_fast_model)
- Deprecated fields kept for backward compatibility

### Performance Improvement
- No routing overhead (direct planner instantiation)
- No indirection through AutoPlanner

### Maintenance Benefits
- Single planner implementation to maintain
- Planning logic co-located with agent loop
- Cleaner config without historical naming

## Risk Mitigation

### Potential Risks

1. **Breaking imports in external code**
   - ClaudePlanner/AutoPlanner were internal (not exported in __init__.py)
   - Low risk

2. **Breaking workflows with "always_claude" config**
   - Claude subagent still available via task tool
   - Config backward compatibility maintained
   - Document migration path

3. **Breaking query classification**
   - Query classification is separate module (unified_classifier.py)
   - Not modified in this consolidation
   - Verify with dedicated tests

4. **Breaking agent loop protocol**
   - LLMPlanner already implements LoopReasonerProtocol
   - Protocol unchanged, just single implementation

### Mitigation Strategies

1. Keep deprecated config fields for backward compatibility
2. Add deprecation warnings if needed
3. Document that Claude subagent available via task tool
4. Run full test suite after each phase
5. Preserve query classification module intact

## Progress Tracking

### Phase 1: Move Utilities ✅
- [ ] Move functions from llm.py to _shared.py
- [ ] Update imports in llm.py
- [ ] Update imports in claude.py (temporarily)
- [ ] Update imports in agent_loop.py (temporarily)
- [ ] Run tests to verify

### Phase 2: Delete Redundant Planners ✅
- [ ] Delete claude.py
- [ ] Delete router.py
- [ ] Remove imports from resolver
- [ ] Delete test_auto_planner.py
- [ ] Run tests to verify

### Phase 3: Simplify Resolver ✅
- [ ] Simplify resolve_planner() logic
- [ ] Remove Claude/Auto planner creation
- [ ] Always return LLMPlanner
- [ ] Run tests to verify

### Phase 4: Simplify Config ✅
- [ ] Add new config fields
- [ ] Keep deprecated fields
- [ ] Update resolver to use new fields
- [ ] Update config.yml files
- [ ] Run tests to verify

### Phase 5: Merge Modules ✅
- [ ] Move llm.py to agent_loop/planner.py
- [ ] Move _shared.py to agent_loop/planning_utils.py
- [ ] Update imports in moved files
- [ ] Update imports throughout codebase
- [ ] Delete planning module directory
- [ ] Run tests to verify

### Phase 6: Update Tests ✅
- [ ] Delete test_auto_planner.py
- [ ] Update imports in test_planning.py
- [ ] Update imports in test_shared_planning.py
- [ ] Update imports in other test files
- [ ] Add new tests
- [ ] Run full test suite

### Phase 7: Documentation ✅
- [ ] Update RFCs
- [ ] Update READMEs
- [ ] Update docstrings
- [ ] Final verification

## Notes

- Query classification remains untouched (separate optimization, RFC-0012)
- LoopReasonerProtocol unchanged (still valid abstraction)
- Claude subagent functionality preserved via task tool
- Two-phase reasoning preserved in LLMPlanner (RFC-604)

## Related Work

- IG-036: Removed SubagentPlanner (similar consolidation)
- IG-028: DirectPlanner→SimplePlanner→LLMPlanner evolution
- RFC-604: Reason phase robustness (LLMPlanner two-phase architecture)