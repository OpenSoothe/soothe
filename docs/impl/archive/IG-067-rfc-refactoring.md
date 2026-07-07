# IG-067: RFC Refactoring and Self-Containment

**Status**: 🔄 In Progress
**Created**: 2026-03-26
**RFC References**: All RFCs in docs/specs/

## Objective

Refactor all RFCs to be self-contained, properly scoped, and correctly cross-referenced. Split large RFCs into focused, independently understandable documents.

## Problem Analysis

### Critical Issues

1. **Oversized RFCs**:
   - RFC-400: 1702 lines (3 transport protocols combined)
   - RFC-600: 1684 lines (plugin API + discovery + security + migration)
   - RFC-401: 1003 lines (event protocol + catalog)
   - RFC-101: 963 lines (architecture + implementation guide)
   - RFC-402: 857 lines (thread lifecycle + REST API)

2. **Non-Self-Contained RFCs**:
   - RFC-200: References RFC-202 without context
   - RFC-500: References RFC-400 for message formats
   - RFC-202: Uses undefined models from RFC-202

3. **Dependency Issues**:
   - Circular dependencies between RFC-500 ↔ RFC-401
   - Circular dependencies between RFC-200 ↔ RFC-202
   - Missing dependency declarations in RFC-402, RFC-501, RFC-201
   - Unnecessary dependencies in RFC-600, RFC-401

## Solution Approach

### Phase 1: Split Large RFCs (Priority Order)

**RFC-400 Split** → 5 focused RFCs:
- RFC-400a: Unix Socket Protocol
- RFC-400b: WebSocket Protocol
- RFC-400c: HTTP REST API
- RFC-400d: Event Bus Architecture
- RFC-400e: Security Model

**RFC-600 Split** → 4 focused RFCs:
- RFC-600a: Plugin API and Decorators
- RFC-600b: Plugin Discovery and Loading
- RFC-600c: Plugin Security Model
- RFC-600d: Plugin Migration Guide (move to impl/)

**RFC-401 Refactor**:
- Keep core protocol (~300 lines)
- Move event catalog to separate reference document

**RFC-101 Refactor**:
- Keep architecture (~400 lines)
- Move implementation steps to IG

**RFC-402 Refactor**:
- Keep thread lifecycle (~400 lines)
- Move REST API to RFC-400c (HTTP REST API)

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

**Current RFC-400 splits** → New RFC numbers:
- RFC-400a → RFC-601: Unix Socket Protocol
- RFC-400b → RFC-401: WebSocket Protocol
- RFC-400c → RFC-100: HTTP REST API
- RFC-400d → RFC-501: Event Bus Architecture
- RFC-400e → RFC-101: Security Model

**Current RFC-600 splits** → New RFC numbers:
- RFC-600a → RFC-0026: Plugin API
- RFC-600b → RFC-0027: Plugin Discovery
- RFC-600c → RFC-0028: Plugin Security

**Note**: Keep original RFC numbers for traceability, add split indicators:
- RFC-400 (superseded) → references RFC-601 through RFC-101
- RFC-600 (superseded) → references RFC-0026 through RFC-0028

## Files to Create

### New RFCs (from splits):
- docs/specs/RFC-601.md (Unix Socket)
- docs/specs/RFC-401.md (WebSocket)
- docs/specs/RFC-100.md (HTTP REST API)
- docs/specs/RFC-501.md (Event Bus)
- docs/specs/RFC-101.md (Security Model)
- docs/specs/RFC-0026.md (Plugin API)
- docs/specs/RFC-0027.md (Plugin Discovery)
- docs/specs/RFC-0028.md (Plugin Security)

### New Reference Documents:
- docs/specs/event-catalog.md (extracted from RFC-401)

### Updated Documents:
- docs/specs/RFC-400.md (mark as superseded, redirect to new RFCs)
- docs/specs/RFC-401.md (remove catalog, keep protocol)
- docs/specs/RFC-101.md (remove implementation steps)
- docs/specs/RFC-402.md (remove REST API)
- docs/specs/RFC-600.md (mark as superseded, redirect to new RFCs)
- docs/specs/rfc-index.md (regenerate)
- docs/specs/rfc-history.md (add splitting entries)

## Implementation Order

1. ✅ Create IG-067 (this document)
2. 🔄 Split RFC-400 → Create RFC-601 through RFC-101
3. ⏳ Split RFC-600 → Create RFC-0026 through RFC-0028
4. ⏳ Refactor RFC-401 (move catalog)
5. ⏳ Refactor RFC-101 (move implementation)
6. ⏳ Refactor RFC-402 (move REST API to RFC-100)
7. ⏳ Make RFCs self-contained (RFC-200, RFC-500, RFC-202)
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