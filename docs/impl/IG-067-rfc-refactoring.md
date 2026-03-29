# IG-067: RFC Refactoring and Self-Containment

**Status**: 🔄 In Progress
**Created**: 2026-03-26
**RFC References**: All RFCs in docs/specs/

## Objective

Refactor all RFCs to be self-contained, properly scoped, and correctly cross-referenced. Split large RFCs into focused, independently understandable documents.

## Problem Analysis

### Critical Issues

1. **Oversized RFCs**:
   - RFC-0013: 1702 lines (3 transport protocols combined)
   - RFC-0018: 1684 lines (plugin API + discovery + security + migration)
   - RFC-0015: 1003 lines (event protocol + catalog)
   - RFC-0016: 963 lines (architecture + implementation guide)
   - RFC-0017: 857 lines (thread lifecycle + REST API)

2. **Non-Self-Contained RFCs**:
   - RFC-0007: References RFC-0009 without context
   - RFC-0003: References RFC-0013 for message formats
   - RFC-0010: Uses undefined models from RFC-0009

3. **Dependency Issues**:
   - Circular dependencies between RFC-0003 ↔ RFC-0015
   - Circular dependencies between RFC-0007 ↔ RFC-0009
   - Missing dependency declarations in RFC-0017, RFC-0020, RFC-0008
   - Unnecessary dependencies in RFC-0018, RFC-0019

## Solution Approach

### Phase 1: Split Large RFCs (Priority Order)

**RFC-0013 Split** → 5 focused RFCs:
- RFC-0013a: Unix Socket Protocol
- RFC-0013b: WebSocket Protocol
- RFC-0013c: HTTP REST API
- RFC-0013d: Event Bus Architecture
- RFC-0013e: Security Model

**RFC-0018 Split** → 4 focused RFCs:
- RFC-0018a: Plugin API and Decorators
- RFC-0018b: Plugin Discovery and Loading
- RFC-0018c: Plugin Security Model
- RFC-0018d: Plugin Migration Guide (move to impl/)

**RFC-0015 Refactor**:
- Keep core protocol (~300 lines)
- Move event catalog to separate reference document

**RFC-0016 Refactor**:
- Keep architecture (~400 lines)
- Move implementation steps to IG

**RFC-0017 Refactor**:
- Keep thread lifecycle (~400 lines)
- Move REST API to RFC-0013c (HTTP REST API)

### Phase 2: Make RFCs Self-Contained

For each RFC with external references:
1. Add inline context for referenced concepts
2. Create "Prerequisites" section for deep dependencies
3. Remove forward references when possible
4. Include minimal examples instead of "see X"

### Phase 3: Fix Dependencies

1. Remove circular dependencies
2. Add missing dependency declarations
3. Remove unnecessary dependencies
4. Update dependency graph in rfc-index.md

### Phase 4: Update Cross-References

1. Update all RFC cross-references in docs/
2. Update RFC references in codebase (CLAUDE.md, implementation guides)
3. Generate new rfc-index.md
4. Update rfc-history.md

## Renumbering Strategy

After splitting, renumber RFCs to maintain clarity:

**Current RFC-0013 splits** → New RFC numbers:
- RFC-0013a → RFC-0021: Unix Socket Protocol
- RFC-0013b → RFC-0022: WebSocket Protocol
- RFC-0013c → RFC-0023: HTTP REST API
- RFC-0013d → RFC-0024: Event Bus Architecture
- RFC-0013e → RFC-0025: Security Model

**Current RFC-0018 splits** → New RFC numbers:
- RFC-0018a → RFC-0026: Plugin API
- RFC-0018b → RFC-0027: Plugin Discovery
- RFC-0018c → RFC-0028: Plugin Security

**Note**: Keep original RFC numbers for traceability, add split indicators:
- RFC-0013 (superseded) → references RFC-0021 through RFC-0025
- RFC-0018 (superseded) → references RFC-0026 through RFC-0028

## Files to Create

### New RFCs (from splits):
- docs/specs/RFC-0021.md (Unix Socket)
- docs/specs/RFC-0022.md (WebSocket)
- docs/specs/RFC-0023.md (HTTP REST API)
- docs/specs/RFC-0024.md (Event Bus)
- docs/specs/RFC-0025.md (Security Model)
- docs/specs/RFC-0026.md (Plugin API)
- docs/specs/RFC-0027.md (Plugin Discovery)
- docs/specs/RFC-0028.md (Plugin Security)

### New Reference Documents:
- docs/specs/event-catalog.md (extracted from RFC-0015)

### Updated Documents:
- docs/specs/RFC-0013.md (mark as superseded, redirect to new RFCs)
- docs/specs/RFC-0015.md (remove catalog, keep protocol)
- docs/specs/RFC-0016.md (remove implementation steps)
- docs/specs/RFC-0017.md (remove REST API)
- docs/specs/RFC-0018.md (mark as superseded, redirect to new RFCs)
- docs/specs/rfc-index.md (regenerate)
- docs/specs/rfc-history.md (add splitting entries)

## Implementation Order

1. ✅ Create IG-067 (this document)
2. 🔄 Split RFC-0013 → Create RFC-0021 through RFC-0025
3. ⏳ Split RFC-0018 → Create RFC-0026 through RFC-0028
4. ⏳ Refactor RFC-0015 (move catalog)
5. ⏳ Refactor RFC-0016 (move implementation)
6. ⏳ Refactor RFC-0017 (move REST API to RFC-0023)
7. ⏳ Make RFCs self-contained (RFC-0007, RFC-0003, RFC-0010)
8. ⏳ Fix dependencies in all RFCs
9. ⏳ Update cross-references in docs/
10. ⏳ Update cross-references in codebase
11. ⏳ Regenerate rfc-index.md
12. ⏳ Update rfc-history.md

## Success Criteria

1. All RFCs < 500 lines (architectural) or < 300 lines (specification)
2. All RFCs self-contained with necessary context inline
3. No circular dependencies
4. All dependencies correctly declared
5. Cross-references updated throughout codebase
6. rfc-index.md reflects new structure
7. rfc-history.md documents the refactoring

## Verification

After refactoring:
```bash
# Check line counts
wc -l docs/specs/RFC-*.md

# Verify no circular dependencies
python scripts/check_rfc_deps.py

# Verify cross-references
grep -r "RFC-" docs/ src/ | grep -v "Binary file"

# Run verification suite
./scripts/verify_finally.sh
```