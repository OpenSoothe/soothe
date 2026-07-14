# Implementation Guide: RFC Renumbering - AgentLoop Specs into 2xx Series

**ID**: IG-295
**Status**: In Progress
**Created**: 2026-05-03
**Scope**: Renumber AgentLoop-related RFCs from scattered series into unified 2xx (Cognition/AgentLoop layer)
**Impact**: 5 RFC files renamed, ~60+ file references updated

---

## Objective

Consolidate AgentLoop-related RFCs scattered across 4xx (Daemon) and 6xx (Plugin) series into the unified 2xx series (Cognition/AgentLoop layer). This aligns RFC numbering with architectural layer organization per RFC-000 conceptual design.

---

## RFC Renumbering Mapping

### Files to Rename

| Current RFC | New RFC | Current Title | New Title | Series Logic |
|-------------|---------|---------------|-----------|--------------|
| RFC-409 | RFC-215 | AgentLoop Persistence Backend Architecture | AgentLoop Persistence Backend | 2xx = AgentLoop core capability, persistence is Layer 2 concern |
| RFC-608 | RFC-216 | AgentLoop Multi-Thread Infinite Lifecycle | AgentLoop Multi-Thread Lifecycle | 2xx = AgentLoop lifecycle management, thread spanning is core Layer 2 feature |
| RFC-609 | RFC-217 | Goal Context Management for AgentLoop | Goal Context Management | 2xx = AgentLoop goal-level context, mirrors CoreAgent context system |
| RFC-611 | RFC-218 | Checkpoint Tree Architecture | AgentLoop Checkpoint Tree Architecture | 2xx = AgentLoop checkpoint structure, tree is Layer 2 persistence model |
| RFC-615 | RFC-219 | Goal Completion Module | Goal Completion Module | 2xx = AgentLoop goal completion logic, consensus detection is Layer 2 cognition |

### Series Rationale

**2xx Series Definition** (from RFC-000):
- Layer 2: AgentLoop orchestration
- Cognition loop: Plan → Execute
- Goal management, thread spanning, working memory
- **Core principle**: AgentLoop-centric specs belong in 2xx

**Misplacement Analysis**:
- RFC-409 (4xx-Daemon): Persistence backend is AgentLoop concern, not daemon transport
- RFC-608/609/611/615 (6xx-Plugin): Core AgentLoop features, not plugin extensions

**Correctly Placed** (no change):
- RFC-503/504 (5xx-CLI): Loop-first UX, CLI commands → user-facing layer
- RFC-411 (4xx-Daemon): Event stream replay → daemon streaming concern

---

## Implementation Phases

### Phase 1: File Renaming (Physical Move)

**Steps**:
1. Rename 5 RFC files in `docs/specs/`
2. Update RFC header metadata (RFC number field)
3. Preserve all content, only change identifiers

**Commands**:
```bash
cd docs/specs

# Rename files
mv RFC-409-agentloop-persistence-backend.md RFC-215-agentloop-persistence-backend.md
mv RFC-608-loop-multithread-lifecycle.md RFC-216-agentloop-multithread-lifecycle.md
mv RFC-609-goal-context-management.md RFC-217-goal-context-management.md
mv RFC-611-checkpoint-tree-architecture.md RFC-218-agentloop-checkpoint-tree-architecture.md
mv RFC-615-goal-completion-module.md RFC-219-goal-completion-module.md
```

**Header Updates** (example for RFC-215 → RFC-215):
```markdown
# AgentLoop Persistence Backend Architecture

> **RFC Number**: RFC-215  # Changed from RFC-409
> **Status**: Draft
> **Created**: 2026-04-22
```

---

### Phase 2: RFC Index & History Updates

**Files to Update**:
- `docs/specs/rfc-index.md`
- `docs/specs/rfc-history.md`

**Changes**:
1. Update RFC catalog entries (renumber in 2xx section)
2. Add renumbering entries to history table
3. Update "Recently Added" section

**Example** (rfc-index.md):
```markdown
### Core Architecture (2xx Series)

- **RFC-215**: [AgentLoop Persistence Backend](RFC-215*.md)
  - Status: Draft
  - Created: 2026-04-22
  - Renamed from: RFC-409 (2026-05-03)

- **RFC-216**: [AgentLoop Multi-Thread Lifecycle](RFC-216*.md)
  - Status: Draft
  - Created: 2026-04-16
  - Renamed from: RFC-608 (2026-05-03)

- **RFC-217**: [Goal Context Management](RFC-217*.md)
  - Status: Draft
  - Created: 2026-04-17
  - Renamed from: RFC-609 (2026-05-03)

- **RFC-218**: [AgentLoop Checkpoint Tree Architecture](RFC-218*.md)
  - Status: Draft
  - Created: 2026-04-22
  - Renamed from: RFC-611 (2026-05-03)

- **RFC-219**: [Goal Completion Module](RFC-219*.md)
  - Status: Draft
  - Created: 2026-04-24
  - Renamed from: RFC-615 (2026-05-03)
```

**History Entry** (rfc-history.md):
```markdown
| 2026-05-03 | RFC-409 → RFC-215 | Renumbered | AgentLoop Persistence Backend moved to 2xx series (architecture alignment) |
| 2026-05-03 | RFC-608 → RFC-216 | Renumbered | AgentLoop Multi-Thread Lifecycle moved to 2xx series |
| 2026-05-03 | RFC-609 → RFC-217 | Renumbered | Goal Context Management moved to 2xx series |
| 2026-05-03 | RFC-611 → RFC-218 | Renumbered | Checkpoint Tree Architecture moved to 2xx series |
| 2026-05-03 | RFC-615 → RFC-219 | Renumbered | Goal Completion Module moved to 2xx series |
```

---

### Phase 3: RFC Cross-References (Internal RFC Links)

**Files**: All RFC specs that reference renamed RFCs

**Update Pattern**:
```regex
# Search patterns
RFC-409 → RFC-215
RFC-608 → RFC-216
RFC-609 → RFC-217
RFC-611 → RFC-218
RFC-615 → RFC-219
```

**Affected RFCs** (found via grep):
- RFC-214: References RFC-409, RFC-608, RFC-611
- RFC-411: References RFC-409, RFC-611
- RFC-503: References RFC-608, RFC-409
- RFC-504: References RFC-409
- RFC-612: References RFC-409 extensively
- RFC-616: References RFC-615
- RFC-207: References RFC-608, RFC-609

**Example Update** (RFC-214 dependencies section):
```markdown
**Dependencies**: RFC-201 (AgentLoop Plan–Execute), RFC-100 (CoreAgent Runtime), 
RFC-206 (Prompt Architecture), RFC-207 (Thread & Goal Context), RFC-203 (AgentLoop State & Memory), 
RFC-215 (AgentLoop Persistence), RFC-218 (Checkpoint Tree), RFC-216 (Multi-Thread Lifecycle)
```

---

### Phase 4: Code Reference Updates

**Scope**: Python source files, test files, CLI/TUI code

**Search Results** (from grep):
- 63 files contain references to RFC-215, RFC-216, RFC-217, RFC-218, RFC-219
- Primary locations:
  - `packages/soothe/src/soothe/cognition/agent_loop/` (core implementations)
  - `packages/soothe/tests/` (test files with RFC references)
  - `packages/soothe-cli/` (CLI/TUI references)
  - `docs/impl/IG-*.md` (implementation guides)

**Update Categories**:

#### 4.1 Source Code Comments
```python
# Example: packages/soothe/src/soothe/cognition/agent_loop/state/persistence/manager.py
# RFC-409: AgentLoop Persistence Backend Architecture
# CHANGE TO:
# RFC-215: AgentLoop Persistence Backend Architecture
```

#### 4.2 Docstring References
```python
"""Save goal execution record (RFC-409).
# CHANGE TO:
"""Save goal execution record (RFC-215).
```

#### 4.3 Implementation Guide References
```markdown
# docs/impl/IG-277-loop-checkpoint-bug-fixes.md
**RFC References**: RFC-216 (Multi-thread spanning), RFC-215 (Persistence backend)
```

---

### Phase 5: Automated Reference Update Script

**Script**: `scripts/update_rfc_references.py` (existing script, update logic)

**Current Script Capabilities**:
- Pattern-based search/replace
- Multiple file format support (md, py)
- Backup creation
- Dry-run mode

**Enhancements Needed**:
1. Add new renumbering mappings
2. Update script documentation
3. Add verification pass (check for missed references)

**Script Update**:
```python
# scripts/update_rfc_references.py

RENUMBERING_MAP = {
    "RFC-409": "RFC-215",
    "RFC-608": "RFC-216",
    "RFC-609": "RFC-217",
    "RFC-611": "RFC-218",
    "RFC-615": "RFC-219",
}

# Add to script's mapping dictionary
# Run with: python scripts/update_rfc_references.py --dry-run
# Then: python scripts/update_rfc_references.py --execute
```

---

## Verification Steps

### Post-Renaming Verification

**Checklist**:
1. ✅ All 5 RFC files renamed correctly
2. ✅ RFC headers updated (number field)
3. ✅ RFC index reflects new numbers
4. ✅ RFC history documents renumbering
5. ✅ All RFC cross-references updated
6. ✅ All code references updated
7. ✅ Implementation guide references updated
8. ✅ No stray old RFC numbers in codebase
9. ✅ Verification script passes (./scripts/verify_finally.sh)

**Grep Verification** (search for old numbers):
```bash
# Should return ZERO results after update
grep -r "RFC-409" docs/ packages/ scripts/ --exclude-dir=.git
grep -r "RFC-608" docs/ packages/ scripts/ --exclude-dir=.git
grep -r "RFC-609" docs/ packages/ scripts/ --exclude-dir=.git
grep -r "RFC-611" docs/ packages/ scripts/ --exclude-dir=.git
grep -r "RFC-615" docs/ packages/ scripts/ --exclude-dir=.git
```

---

## Rollback Plan

**If issues detected**:
1. Revert file renames (mv back to original names)
2. Revert RFC index/history (git checkout)
3. Revert code references (use git reset or backup files)
4. Document rollback reason
5. Fix issues, retry with updated script

---

## Implementation Tasks

### Task Breakdown

1. **File Renaming** (5 files)
   - Rename RFC files
   - Update RFC header metadata

2. **Index Updates** (2 files)
   - Update rfc-index.md
   - Update rfc-history.md

3. **Cross-Reference Updates** (10+ RFC files)
   - Update dependencies sections
   - Update inline references

4. **Code Updates** (63 files)
   - Update source code comments
   - Update docstrings
   - Update IG references

5. **Script Enhancement**
   - Update update_rfc_references.py
   - Add new mappings
   - Test dry-run mode

6. **Verification**
   - Grep checks (zero old references)
   - Run verify_finally.sh
   - Manual review of critical files

---

## Success Criteria

1. All RFC files renamed and indexed in 2xx series ✅
2. RFC index/history accurately reflect renumbering ✅
3. Zero stray old RFC numbers in codebase (grep verification) ✅
4. All tests pass (./scripts/verify_finally.sh) ✅
5. RFC catalog total count preserved (46 RFCs) ✅
6. Series organization aligns with RFC-000 architecture ✅

---

## Related Documents

- RFC-000: System Conceptual Design (series definitions)
- RFC-001: Core Modules Architecture (layer organization)
- RFC history: 2026-03-31 reclassification event (previous renumbering)
- scripts/update_rfc_references.py (automation tool)

---

## Implementation Notes

**Execution Order**:
1. Phase 1-2 manual (file operations, index updates)
2. Phase 3-4 automated (script-based bulk updates)
3. Phase 5 verification (grep checks, test suite)

**Time Estimate**:
- Phase 1-2: 15 minutes (manual)
- Phase 3-4: 5 minutes (script execution)
- Phase 5: 10 minutes (verification)
- **Total**: ~30 minutes

**Risk Level**: Low
- Pure renaming, no logic changes
- Reversible via git revert
- Automated bulk updates reduce manual error

---

**End of IG-295 Implementation Guide**