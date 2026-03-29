# IG-098: RFC-0011 Deprecation Cleanup

## Overview

Remove the deprecated RFC-0011 (Dynamic Goal Management) and update all references to point to RFC-0007, where the content has been merged.

## Context

RFC-0011 has been officially deprecated and merged into RFC-0007 (Layer 3: Autonomous Goal Management Loop). The deprecation notice states:
- GoalDirective model → RFC-0007 §5.4
- GoalContext model → RFC-0007 §5.4
- Enhanced PlannerProtocol.reflect() → RFC-0007 §5.4
- DAG consistency handling → RFC-0007 §5.5
- Safety mechanisms → RFC-0007 §5.6

## Scope

### Files to Delete
- `docs/specs/RFC-0011-dynamic-goal-management.md`

### Files to Update
1. **Index Files**: Update RFC index to remove RFC-0011 entry
2. **User Guide**: Remove RFC-0011 reference
3. **Source Code**: Update docstring references from RFC-0011 → RFC-0007
4. **Config Files**: Update comments from RFC-0011 → RFC-0007
5. **Implementation Guides**: Preserve historical context but update status

## Implementation Steps

### Phase 1: Delete RFC-0011 File
Remove the deprecated RFC file completely.

### Phase 2: Update RFC Index
Update `docs/specs/rfc-index.md`:
- Remove RFC-0011 from active RFC table
- Remove from deprecated section (already marked deprecated)
- Update counts

### Phase 3: Update User Guide
Update `docs/user_guide.md` to remove RFC-0011 reference.

### Phase 4: Update Source Code Docstrings
Update all code references:
- `src/soothe/protocols/planner.py`: Update GoalDirective, GoalContext, Reflection docstrings
- `src/soothe/config/models.py`: Update AutonomousConfig docstrings
- `src/soothe/cognition/planning/_shared.py`: Update reflection function docstrings
- `src/soothe/cognition/planning/claude.py`: Update docstrings
- `src/soothe/core/runner/_runner_autonomous.py`: Update comments
- `src/soothe/core/runner/_runner_goal_directives.py`: Update docstrings

Change pattern: `(RFC-0011)` → `(RFC-0007 §5.4-5.6)` or just `(RFC-0007)` depending on context.

### Phase 5: Update Configuration Files
Update config comments:
- `config.dev.yml`: Change RFC-0011 → RFC-0007 in autonomous config
- `src/soothe/config/config.yml`: Change RFC-0011 → RFC-0007

### Phase 6: Update Test Files
Update `tests/unit/test_dynamic_goals.py` docstring.

### Phase 7: Update Implementation Guides
For IGs documenting historical work (IG-028, IG-029):
- Preserve historical accuracy
- Add note: "[Completed - RFC-0011 merged into RFC-0007]"
- Update current status sections

For IG-067 (rfc-refactoring):
- Update task status to reflect completion

### Phase 8: Update Draft Documents
For recent drafts mentioning RFC-0011:
- Update to reflect current state (merged into RFC-0007)
- Preserve decision-making history

### Phase 9: Update Review/Validation Reports
These are historical snapshots - preserve as-is or add notes.

## Verification

After all updates:
1. Run `grep -i "RFC-0011"` to verify no remaining references
2. Run `./scripts/verify_finally.sh` to ensure no code breaks
3. Check that RFC-0007 properly documents all merged content

## Success Criteria

1. No file named RFC-0011 exists in `docs/specs/`
2. All code docstrings reference RFC-0007 instead of RFC-0011
3. Configuration comments reference RFC-0007
4. RFC index properly reflects deprecation
5. All tests pass
6. No grep results for RFC-0011 in active code/specs