# IG-296: Deprecate and Migrate Legacy Core Code

## Summary

Systematically deprecate and migrate legacy fields and backward compatibility code in soothe.core module to eliminate architectural violations and technical debt.

## Context

**Problem**: soothe.core contains:
- 2 deprecated fields requiring migration (30+ usage sites)
- 4 backward compatibility patterns violating RFC architecture
- 5 potentially dead modules dependent on legacy paths

**Timeline**: 8-12 weeks total (Phase 3: 4-6 weeks, Phase 4: 2-3 weeks, Phase 5: 1 week)

**Approach**: Add deprecation warnings → Monitor → Migrate → Remove

---

## Phase 3: Deprecate Fields with Migration

### 3.1 unified_classification → intent_classification

**File**: `packages/soothe/src/soothe/core/runner/_types.py:101`

**Current State**:
- Comment: "deprecated, use intent_classification"
- 18+ usage sites across runner modules
- IG-226 introduced IntentClassification with goal handling strategy

**Migration Steps**:

1. Add backward compatibility property with DeprecationWarning
2. Run tests with warnings enabled to identify usage sites
3. Systematically update all 18+ usage sites
4. Remove deprecated field after 2-week zero-warning period

**Usage Sites** (grep "unified_classification"):
- `_runner_phases.py`
- `_runner_steps.py`
- `_runner_agentic.py`
- `routing_merge.py`

### 3.2 _query_running → _active_threads

**File**: `packages/soothe/src/soothe/daemon/server.py:106`

**Current State**:
- Comment: "Deprecated: use _active_threads instead"
- Internal daemon field

**Migration Steps**:
1. Add property with DeprecationWarning
2. Migrate daemon internal usage
3. Remove field after validation

---

## Phase 4: Remove Backward Compatibility Code

### 4.1 Legacy Execution Path (Architectural Violation)

**File**: `packages/soothe/src/soothe/core/runner/_runner_autonomous.py:592-636`

**Current State**:
- Warning: "Using legacy execution path (no AgentLoop) - violates RFC architecture"
- Fallback for goals without LoopPlannerProtocol planner

**Removal Steps**:
1. Validate all planners use AgentLoop (check backends/planning/)
2. Add assertion that planner must provide AgentLoop
3. Remove legacy execution code (592-636)
4. Update docstring

**Critical**: RFC architecture violation - mandatory removal

### 4.2 Legacy Backend String Parameter

**File**: `packages/soothe/src/soothe/core/agent_loop/state/persistence/manager.py:38-44`

**Current State**:
- Accepts string "sqlite"/"postgresql" for backward compatibility
- Logs warning when legacy string passed

**Removal Steps**:
1. Add DeprecationWarning
2. Migrate callers to pass SootheConfig
3. Remove string parameter acceptance

### 4.3 Legacy Flat Plan Parsing

**File**: `packages/soothe/src/soothe/core/agent_loop/utils/reflection.py:457-469`

**Current State**:
- Parses legacy plan shape (steps at root, no plan fields)
- Error: "Failed to parse legacy plan shape"

**Removal Steps**:
1. Validate all planners use new PlanResult schema
2. Remove legacy parsing code
3. Simplify plan parsing logic

### 4.4 Legacy Stream Output Collection

**File**: `packages/soothe/src/soothe/core/agent_loop/core/executor.py:737`

**Current State**:
- Comment: "Still collect for legacy compatibility"
- Collects output for legacy clients

**Removal Steps**:
1. Audit client usage (daemon, CLI, SDK)
2. Remove if modern clients validated

---

## Phase 5: Remove Potentially Dead Modules

**Dependencies**: Requires Phase 4.1 completion (legacy path removal)

### Modules to Investigate:

1. **goal_engine/discovery.py** - autopilot discovery, only used by legacy path
2. **goal_engine/consensus.py** - goal consensus, only used by legacy path
3. **goal_engine/criticality.py** - MUST goal evaluator, only used by legacy path
4. **agent_loop/analysis/thread_relevance.py** - exported but never imported
5. **agent_loop/utils/json_parsing.py** - exported but never imported externally

**Decision**: Remove if no usage after Phase 4.1 validation

---

## Implementation Strategy

**Phase 3 Completed**: Week 1-5 completed in single session (migrated unified_classification)
**Phase 4 Remaining**: Week 6-7 (backward compatibility removal) - deferred to future IG-297
**Phase 5 Remaining**: Week 8 (module removal) - dependent on Phase 4

**Recommendation**: Create separate IG-297 for Phase 4-5 work with 2-3 week timeline for production validation and monitoring. These changes require careful testing beyond unit test suite.

---

## Verification

**Level 3**: Integration tests with deprecation warnings
```bash
PYTHONWARNINGS=default::DeprecationWarning ./scripts/verify_finally.sh
```

**Level 5**: Production monitoring for zero warnings before removal

---

## Status

**Phase 3** (COMPLETED):
- [x] IG created
- [x] Migrated 30+ unified_classification usage sites to intent_classification
- [x] Removed deprecated unified_classification field from RunnerState
- [x] Verification passed (1490 tests)
- [x] Committed (0027a5ca)

**Phase 4** (FUTURE WORK - requires careful validation):
- [ ] Remove legacy execution path (RFC violation) - complex, needs production testing
- [ ] Remove legacy backend string parameter - medium complexity
- [ ] Remove legacy flat plan parsing - needs planner schema validation
- [ ] Remove legacy stream output collection - needs client audit

**Phase 5** (DEPENDENT on Phase 4):
- [ ] Remove potentially dead modules after backward compat removal

**Recommendation**: Phase 4-5 work should be separate IG (IG-297) with 2-3 week timeline for proper validation and production monitoring.