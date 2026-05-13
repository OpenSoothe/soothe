# Specs Refinement Report

**Date**: 2026-05-13
**Scope**: All 56 RFC files in `docs/specs/`
**Baseline**: `rfc-standard.md` (3 spec kinds, 5 lifecycle states)

---

## Executive Summary

The RFC corpus is **structurally functional** but has **systemic issues** that reduce its reliability as a source of truth. The most impactful problems are:

1. **Cross-reference confusion between RFC-400/401/402/403** — multiple RFCs conflate which number covers which topic
2. **RFC number mismatches in document headers** — 2 files have wrong RFC numbers in their headers
3. **Wrong RFC numbers in document footers** — 3 files end with a different RFC number than their filename
4. **Lifecycle state contradictions** — 5 RFCs have conflicting status indicators
5. **Missing "Kind" field** — 8 RFCs don't declare their spec kind
6. **Pervasive spec-kind scope creep** — nearly all RFCs contain content exceeding their declared kind

No content was modified during this refinement; this report documents findings and recommends corrections.

---

## 1. Structure Compliance

### 1.1 Spec Kind Classification

The RFC standard defines 3 spec kinds with strict content boundaries:

| Kind | Should Contain | Should NOT Contain |
|------|---------------|-------------------|
| Conceptual Design | Principles, abstractions, terminology, invariants | Concrete schemas, API definitions, implementation code |
| Architecture Design | Components, layers, data flow, abstract schemas | Concrete API signatures, language-specific code |
| Implementation Interface | Type definitions, API contracts, naming conventions | Implementation algorithms, business logic |

**Findings**:

| Kind | Declared Count | Correctly Scoped |
|------|---------------|-----------------|
| Conceptual Design | 1 (RFC-000) | Partial — contains concrete Pydantic models and Python Protocol signatures |
| Architecture Design | 37 | Partial — most contain concrete Python code, SQL schemas, or config YAML |
| Implementation Interface Design | 10 | Partial — most contain full implementation algorithms |
| Not stated | 8 | N/A |
| Dual kind (non-standard) | 2 (RFC-602, RFC-606) | Invalid per standard |

**Systemic issue**: The "Does NOT Contain" rules are consistently violated across all spec kinds. This suggests the standard's boundaries are too strict for the project's practical needs, or the RFCs were written without referencing the standard.

### 1.2 Missing "Kind" Field

8 RFCs do not declare their spec kind in their header:

- RFC-203 (has dual kind "Architecture / Impl Interface")
- RFC-215 (header uses blockquote format, no Kind field)
- RFC-218 (header uses blockquote format, no Kind field)
- RFC-300 (no Kind field)
- RFC-411 (no Kind field)
- RFC-454 (no Kind field)
- RFC-503 (no Kind field)
- RFC-504 (no Kind field)
- RFC-603 (uses "Type: Feature Enhancement" instead)
- RFC-612 (no Kind field)
- RFC-616 (no Kind field)
- RFC-602 (dual kind)
- RFC-606 (dual kind)

### 1.3 Header Format Inconsistency

RFC headers use at least 4 different formats:

1. **Bold key-value** (most common): `**RFC**: RFC-200`, `**Status**: Draft`
2. **Blockquote format**: `> RFC: 215`, `> Status: Draft`
3. **Mixed bold with extra fields**: `**RFC Number**: RFC-102`, `**Author**: System`
4. **Numbered sections**: RFC-101, RFC-301, RFC-401, RFC-403 use numbered section headings (1-11, 1-15)

Non-standard author values found: "System", "Platonic brainstorming session", "Claude Sonnet 4.6"

### 1.4 Missing Standard Sections

Common omissions across RFCs:

| Missing Section | Affected RFCs |
|----------------|--------------|
| Changelog | RFC-215, RFC-218, RFC-219, RFC-220, RFC-221, RFC-300, RFC-411, RFC-452, RFC-454 |
| Configuration | RFC-219, RFC-221, RFC-411, RFC-454, RFC-617 |
| Design Principles | RFC-221, RFC-411, RFC-454 |
| Scope and Non-Goals | RFC-502, RFC-602, RFC-603, RFC-605, RFC-606, RFC-612, RFC-616, RFC-617 |
| Implementation Status | RFC-220, RFC-221, RFC-300, RFC-411, RFC-452, RFC-454 |
| References | RFC-215, RFC-218 |

---

## 2. Cross-Reference Integrity

### 2.1 RFC Number Mismatches (CRITICAL)

| File | Header Says | Should Be | Severity |
|------|------------|-----------|----------|
| RFC-401-event-processing.md | `**RFC**: 451` | 401 | Critical |
| RFC-403-unified-event-naming.md | `**RFC**: 453` | 403 | Critical |

### 2.2 Footer Number Mismatches

| File | Footer Says | Should Be |
|------|------------|-----------|
| RFC-215-agentloop-persistence-backend.md | "End of RFC-613 Draft" | RFC-215 |
| RFC-411-event-stream-replay.md | "End of RFC-614 Draft" | RFC-411 |
| RFC-503-loop-first-user-experience.md | "End of RFC-612 Draft" | RFC-503 |
| RFC-504-loop-management-cli-commands.md | "End of RFC-219 Draft" | RFC-504 |

These suggest documents were renumbered without updating the footer.

### 2.3 Cross-Reference Confusion: RFC-400/401/402/403

The most pervasive cross-reference problem. Multiple RFCs conflate which number covers which topic:

| Topic | Correct RFC | Commonly Misattributed To |
|-------|------------|--------------------------|
| ContextProtocol Architecture | RFC-400 | Often correctly referenced |
| Event Processing & Filtering | RFC-401 | Frequently called "RFC-400" by other RFCs |
| MemoryProtocol Architecture | RFC-402 | Sometimes called "Unified Event Naming" |
| Unified Event Naming | RFC-403 | Sometimes called "RFC-402" |

**Specific errors**:
- RFC-401 section 4 says "naming conventions defined in RFC-402" — should be RFC-403
- RFC-403 section 11 says "RFC-402 (Unified Event Naming)" — should be RFC-403 (self-reference) or RFC-402 is MemoryProtocol
- RFC-403 section 2.2 references "RFC-400" for event processing — should be RFC-401
- RFC-403 section 14 References lists "RFC-400: Event Processing & Filtering" — should be RFC-401
- RFC-454 Abstract says "extends RFC-400" but Dependencies say "RFC-450" — RFC-450 is correct
- RFC-600 References lists RFC-400 twice with different titles

### 2.4 Non-Existent RFC References

References to RFC numbers that don't exist in the current corpus:

| Reference | Found In | Notes |
|-----------|----------|-------|
| RFC-002 | RFC-216 | Likely old numbering; no RFC-002 exists in current scheme |
| RFC-173, RFC-174, RFC-175 | RFC-610 | These are IG numbers (IG-173/174/175), not RFCs |
| RFC-451 | RFC-204 | RFC-451 does not exist (likely confused with RFC-450) |
| RFC-0011 | RFC-200 | Old numbering; no RFC-0011 in current scheme |
| RFC-0002, RFC-0013 | RFC-612, RFC-301 | Old numbering from pre-reclassification |
| RFC-0004, RFC-0005, RFC-0021 | RFC-601 | Old numbering (merged into RFC-601) |
| RFC-0015 | RFC-401, RFC-403 | Old numbering (merged into RFC-400) |
| RFC-0016, RFC-0025 | RFC-101 | Old numbering (merged into RFC-101) |
| RFC-0019, RFC-0022 | RFC-401 | Old numbering (merged into RFC-400) |
| RFC-0020, RFC-0024 | RFC-501 | Old numbering (merged into RFC-501) |
| RFC-0008 | RFC-603, RFC-604 | Old numbering (now part of RFC-200) |
| RFC-183 | RFC-206 | Unclear; may be old numbering |

### 2.5 Self-Referencing Changelogs

These RFCs have changelogs claiming consolidation from themselves:

- RFC-203: "Consolidated RFC-203, RFC-203, RFC-203"
- RFC-207: "Consolidated RFC-207, RFC-207, RFC-207, RFC-207"
- RFC-213: Similar pattern

These should cite the distinct predecessor RFC numbers that were merged.

---

## 3. Data Model Inconsistencies

### 3.1 ThreadMetadata Conflict

| Field | RFC-408 (Durability) | RFC-452 (Thread Management) |
|-------|---------------------|---------------------------|
| `labels` | `dict[str, str]` | `list[str]` |
| `priority` | `int` | `Literal["low", "normal", "high"]` |

### 3.2 ThreadLifecycle States Conflict

| RFC-408 | RFC-452 |
|---------|---------|
| active, suspended, archived | idle, running, suspended, archived, error, deleted |

### 3.3 PlannerProtocol Interface Drift

| Aspect | RFC-301 (Protocol Registry) | RFC-404 (PlannerProtocol Architecture) |
|--------|---------------------------|--------------------------------------|
| `reason()` method | Defined | Not defined |
| `PlanStatus` values | Includes "revised" | Does not include "revised" |

### 3.4 Permission Model Representation

| RFC-301 | RFC-406 |
|---------|---------|
| `dataclass(frozen=True)` | `BaseModel` (Pydantic) |

---

## 4. Lifecycle State Contradictions

| RFC | Header Status | Implementation Status | Conflict |
|-----|--------------|----------------------|----------|
| RFC-100 | Draft | "Status: Implemented" (with checkmark) | Header says Draft, body says Implemented |
| RFC-104 | Implemented | All Success Criteria unchecked `[ ]` | Implemented but nothing verified |
| RFC-204 | Implemented | 12 gaps documented (many "Missing") | Implemented but gaps exist |
| RFC-402 | Draft | All Implementation Status items checked | Should be Implemented |
| RFC-406 | Draft | All Implementation Status items checked | Should be Implemented |
| RFC-604 | Implemented | Footer says "Draft - Ready for Implementation Guide" | Contradictory |

### Unused Lifecycle States

The standard defines 5 lifecycle states: Draft → Proposed → Accepted → Implemented → Deprecated. In practice:

- **Proposed**: Never used by any RFC
- **Accepted**: Never used by any RFC
- **Deprecated**: Never used by any RFC
- Only **Draft** (38) and **Implemented** (18) are used

---

## 5. Content Scope Issues

### 5.1 Overlapping Scope (RFC-207, RFC-216, RFC-217)

Three RFCs define the same concepts with overlapping definitions:

| Concept | RFC-207 | RFC-216 | RFC-217 |
|---------|---------|---------|---------|
| GoalContextManager | Defined | Defined | Defined |
| ThreadRelationshipModule | Defined | — | Defined |
| Thread-switch detection | Defined | Defined | Defined |
| Thread health metrics | — | Defined | Partial |

RFC-207's changelog says it consolidated content from RFC-216 and RFC-217, yet all three remain as separate active Drafts.

### 5.2 RFC-214 Amendment Sprawl

RFC-214 amends 3 other RFCs in-place (RFC-104, RFC-206, RFC-217), creating split-brain documents where the original text is partially superseded by the amendment in a different RFC. The amended RFCs' main bodies remain unchanged.

### 5.3 RFC-300 vs RFC-400/402 Overlap

RFC-300 (Context and Memory Architecture) was the original combined spec. RFC-400 and RFC-402 were later extracted. RFC-300 still exists as "Implemented" while the extracted RFCs are "Draft", creating conflicting information:

- RFC-400 says KeywordContext is "not yet implemented — critical gap"
- RFC-300 says KeywordContext is implemented
- RFC-400 defines `project_for_subagent()` and `get_retrieval_module()` not in RFC-300

---

## 6. Formatting Issues

| Issue | Affected RFCs |
|-------|--------------|
| Duplicate H1 title | RFC-607 ("Progressive Display Refinements Post-Migration: Progressive Display Refinements Post-Migration") |
| Duplicate RFC number header field | RFC-450 (`**RFC**: 450` and `**Number**: 450`) |
| Component numbering errors | RFC-200 (1, 2, 2.1, 3, 4, 3.0, 3.1, 4, 5, 6, 7) |
| Duplicate section numbering | RFC-403 (two sections labeled "8.4") |
| Empty section | RFC-201 ("Plan Metrics Enhancement" H3 is empty) |
| Developer-specific paths in examples | RFC-104 (`/Users/chenxm/Workspace/Soothe`) |
| Duplicate ContextConstructionOptions | RFC-217 (defined twice with different formatting) |
| Event naming non-compliance | RFC-411 (uses past-tense `goal.created` instead of present-progressive `goal.creating` per RFC-403) |

---

## 7. Recommendations

### Priority 1 — Fix Incorrect Cross-References (High Impact)

1. **RFC-401 header**: Change `**RFC**: 451` → `**RFC**: 401`
2. **RFC-403 header**: Change `**RFC**: 453` → `**RFC**: 403`
3. **RFC-401 section 4**: Change "RFC-402" (for naming) → "RFC-403"
4. **RFC-403 section 11**: Change "RFC-402 (Unified Event Naming)" → "RFC-403"
5. **RFC-403 section 2.2**: Change "RFC-400" (for event processing) → "RFC-401"
6. **RFC-403 section 14**: Change "RFC-400: Event Processing & Filtering" → "RFC-401"
7. **RFC-454 Abstract**: Change "extends RFC-400" → "extends RFC-450"
8. **RFC-600 References**: Fix duplicate RFC-400 entry with correct titles
9. **RFC-610**: Change RFC-173/174/175 → IG-173/IG-174/IG-175

### Priority 2 — Fix Footer Mismatches

1. **RFC-215 footer**: Change "End of RFC-613 Draft" → "End of RFC-215 Draft"
2. **RFC-411 footer**: Change "End of RFC-614 Draft" → "End of RFC-411 Draft"
3. **RFC-503 footer**: Change "End of RFC-612 Draft" → "End of RFC-503 Draft"
4. **RFC-504 footer**: Change "End of RFC-219 Draft" → "End of RFC-504 Draft"

### Priority 3 — Resolve Data Model Conflicts

1. **ThreadMetadata**: Align `labels` and `priority` types between RFC-408 and RFC-452
2. **ThreadLifecycle**: Unify state enum between RFC-408 and RFC-452
3. **PlannerProtocol**: Align `reason()` method and `PlanStatus` values between RFC-301 and RFC-404
4. **Permission model**: Choose `dataclass` or `BaseModel` consistently across RFC-301 and RFC-406

### Priority 4 — Resolve Lifecycle Contradictions

1. **RFC-100**: Set header status to "Implemented" (matches body)
2. **RFC-104**: Verify success criteria and update status accordingly
3. **RFC-204**: Downgrade to "Draft" or close documented gaps
4. **RFC-402, RFC-406**: Upgrade to "Implemented" (all items checked)

### Priority 5 — Resolve Overlapping Scope

1. **RFC-207/216/217**: Decide whether RFC-207 truly supersedes the others. If so, mark RFC-216 and RFC-217 as Deprecated. If not, clearly delineate boundaries.
2. **RFC-300 vs RFC-400/402**: Mark RFC-300 as Deprecated in favor of the extracted RFCs, or clearly state it as the authoritative overview.
3. **RFC-605 vs RFC-613**: RFC-613 supersedes RFC-605 for the Explore Agent; update RFC-605 status.

### Priority 6 — Add Missing Kind Fields

Add `**Kind**: <type>` to all 8 RFCs that lack it:
- RFC-203 (choose one: Architecture or Impl Interface, not both)
- RFC-215, RFC-218 → Architecture Design
- RFC-300 → Architecture Design
- RFC-411, RFC-454 → Architecture Design
- RFC-503, RFC-504 → Architecture Design / Implementation Interface Design
- RFC-603, RFC-612, RFC-616 → Architecture Design
- RFC-602, RFC-606 → Choose one kind (not dual)

### Priority 7 — Update RFC Standard (Low Priority)

Consider relaxing the standard's "Does NOT Contain" rules since they are systematically violated. Options:

1. Add a "Detailed Architecture" kind that permits concrete schemas and code examples
2. Allow RFCs to have a "Companion IG" relationship where the RFC can reference implementation details in a linked IG
3. Accept the current practice and update the standard to match reality

---

## 8. RFC Index Updates

The previous `rfc-index.md` listed 52 RFCs. This refinement identified 4 missing entries:

- RFC-100 (CoreAgent Runtime Architecture)
- RFC-101 (Tool Interface & Event Naming)
- RFC-102 (Secure Filesystem Path Handling)
- RFC-103 (Thread-Aware Workspace)
- RFC-104 (Dynamic System Context Injection)
- RFC-411 (Event Stream Replay)
- RFC-503 (Loop-First User Experience)
- RFC-504 (Loop Management CLI Commands)

The updated index now includes all 56 RFC files with their spec kinds, status, and cross-references.

---

## 9. Files Modified by This Refinement

| File | Action |
|------|--------|
| `docs/specs/rfc-index.md` | Updated: added 4 missing RFCs, spec kinds, corrected totals |
| `docs/specs/rfc-refinement-report.md` | Created: this report |

**No RFC content files were modified.** All findings are documented here for team review and manual correction.
