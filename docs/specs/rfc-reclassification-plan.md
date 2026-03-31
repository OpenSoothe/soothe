# RFC Reclassification Plan

**Status**: Draft
**Authors**: Xiaming Chen
**Created**: 2026-03-31
**Last Updated**: 2026-03-31
**Depends on**: RFC-0001, RFC-0002
**Supersedes**: ---
**Kind**: Architecture Design

---

## 1. Abstract

This document proposes a reclassification of all RFC specifications in the Soothe project, introducing a numeric prefix system (0xx–6xx) to organize RFCs by subsystem domain. The plan consolidates 23 existing RFCs into 14 well-structured documents, balancing fluency of content with separation of concerns, while respecting Platonic Coding RFC kinds (Conceptual, Architecture, Implementation Interface).

---

## 2. Scope and Non-Goals

### 2.1 Scope

This plan defines:

* Numeric prefix classification (0xx through 6xx) for RFC organization
* Consolidation rules for merging related RFCs
* Kind assignment (Conceptual, Architecture, Impl Interface) per RFC
* Migration mapping from current RFC numbers to new numbers
* Reference document classification (non-RFC supporting files)

### 2.2 Non-Goals

This plan does **not** define:

* Content changes within individual RFCs (separate migration tasks)
* Implementation timeline or sprint planning
* Tooling or automation scripts for migration

---

## 3. Background & Motivation

### 3.1 Current State Problems

The current RFC numbering (0001–0025) has several issues:

1. **No categorical grouping** — RFC-0013 (Daemon) and RFC-0022 (Event Filtering) are numerically distant but thematically related
2. **Fragmented content** — Event processing spans RFC-0015, RFC-0019, RFC-0022, RFC-0024, RFC-0025
3. **No growth room** — Adding new daemon RFCs requires arbitrary numbers (0026+)
4. **Kind inconsistency** — Some RFCs mix conceptual principles with implementation contracts

### 3.2 Goals

1. **Instant category identification** — RFC-4xx is always daemon, RFC-2xx is always cognition
2. **Logical consolidation** — Merge tightly coupled topics into single fluent documents
3. **Kind alignment** — Each RFC has one clear kind following Platonic Coding templates
4. **Room for growth** — 99 slots per category, no renumbering needed

---

## 4. Classification Structure

### 4.1 Numeric Prefix System

| Prefix | Category | Focus |
|--------|----------|-------|
| **0xx** | Foundation | Cross-cutting concepts, system-wide design |
| **1xx** | Core Agent | Runtime, execution, tools, subagents |
| **2xx** | Cognition Loop | Goal management, planning, agentic loops |
| **3xx** | Protocols | Interface contracts, backend abstractions |
| **4xx** | Daemon | Transport, communication, event filtering |
| **5xx** | CLI/TUI | User interface, display, interaction |
| **6xx** | Plugin System | Extension, discovery, lifecycle, built-in agents |

### 4.2 Kind Distribution

| Kind | Purpose | Sections |
|------|---------|----------|
| **Conceptual Design** | Principles, abstractions, taxonomy | Design Principles, Conceptual Model, Taxonomy, Invariants |
| **Architecture Design** | Components, diagrams, data flow | Architecture Overview, Components, Data Flow, Abstract Schemas |
| **Impl Interface Design** | Contracts, naming, data structures | Naming Conventions, Data Structures, Interface Contracts, Implementation Patterns |

---

## 5. Proposed RFC Structure (14 Documents)

### 5.1 Foundation (0xx) — 2 RFCs

| RFC | Kind | Title | Source | Est. Lines |
|-----|------|-------|--------|------------|
| **RFC-000** | Conceptual | System Conceptual Design | RFC-0001 | ~400 |
| **RFC-001** | Architecture | Core Modules Architecture | RFC-0002 | ~500 |

### 5.2 Core Agent Runtime (1xx) — 3 RFCs

| RFC | Kind | Title | Source | Est. Lines |
|-----|------|-------|--------|------------|
| **RFC-100** | Architecture | CoreAgent Runtime (Layer 1) | RFC-0023 | ~400 |
| **RFC-101** | Impl Interface | Tool Interface & Event Naming | RFC-0016 + RFC-0025 | ~450 |
| **RFC-102** | Impl Interface | Security & Filesystem Policy | RFC-0012 | ~400 |

### 5.3 Cognition Loop (2xx) — 3 RFCs

| RFC | Kind | Title | Source | Est. Lines |
|-----|------|-------|--------|------------|
| **RFC-200** | Architecture | Autonomous Goal Management (Layer 3) | RFC-0007 | ~500 |
| **RFC-201** | Architecture | Agentic Goal Execution (Layer 2) | RFC-0008 | ~400 |
| **RFC-202** | Architecture | DAG Execution & Failure Recovery | RFC-0009 + RFC-0010 | ~600 |

### 5.4 Protocols (3xx) — 2 RFCs

| RFC | Kind | Title | Source | Est. Lines |
|-----|------|-------|--------|------------|
| **RFC-300** | Impl Interface | Context & Memory Protocols | RFC-0006 | ~500 |
| **RFC-301** | Impl Interface | Protocol Registry | NEW (6 protocols) | ~500 |

### 5.5 Daemon (4xx) — 2 RFCs

| RFC | Kind | Title | Source | Est. Lines |
|-----|------|-------|--------|------------|
| **RFC-400** | Architecture | Daemon Communication Protocol | RFC-0013 | ~500 |
| **RFC-401** | Impl Interface | Event Processing & Filtering | RFC-0015 + RFC-0019 + RFC-0022 | ~600 |

### 5.6 CLI/TUI (5xx) — 2 RFCs

| RFC | Kind | Title | Source | Est. Lines |
|-----|------|-------|--------|------------|
| **RFC-500** | Architecture | CLI/TUI Architecture | RFC-0003 | ~400 |
| **RFC-501** | Impl Interface | Display & Verbosity | RFC-0020 + RFC-0024 | ~500 |

### 5.7 Plugin System (6xx) — 2 RFCs

| RFC | Kind | Title | Source | Est. Lines |
|-----|------|-------|--------|------------|
| **RFC-600** | Architecture | Plugin Extension System | RFC-0018 | ~600 |
| **RFC-601** | Architecture | Built-in Plugin Agents | RFC-0004 + RFC-0005 + RFC-0021 | ~600 |

---

## 6. Consolidation Rules

### 6.1 Merge Criteria

Merge RFCs when:

| Criterion | Example |
|-----------|---------|
| Same domain prefix | Tool Interface + Event Naming → both 1xx |
| Tight thematic coupling | DAG Execution + Failure Recovery (execution and its failure handling) |
| One supplies context for another | VerbosityTier defines Display tiers |
| All same kind | 0015 + 0019 + 0022 all Impl Interface |

### 6.2 Keep Separate Criteria

Keep RFCs separate when:

| Criterion | Example |
|-----------|---------|
| Different kind | Conceptual vs Architecture |
| Already comprehensive | RFC-0018 (600+ lines, complete) |
| Distinct layer | Layer 1 vs Layer 2 vs Layer 3 |
| Sensitive domain | Security Policy (careful changes) |
| Entry point | CLI/TUI Architecture (user-facing) |

---

## 7. Migration Map

```
Current RFC          New RFC        Kind        Action
─────────────────────────────────────────────────────────────
RFC-0001             RFC-000        Conceptual  KEEP (rename)
RFC-0002             RFC-001        Architecture KEEP (rename)
RFC-0023             RFC-100        Architecture KEEP (rename)
RFC-0016 + RFC-0025  RFC-101        Impl Interface MERGE
RFC-0012             RFC-102        Impl Interface KEEP (rename)
RFC-0007             RFC-200        Architecture KEEP (rename)
RFC-0008             RFC-201        Architecture KEEP (rename)
RFC-0009 + RFC-0010  RFC-202        Architecture MERGE
RFC-0006             RFC-300        Impl Interface KEEP (rename)
(new)                RFC-301        Impl Interface CREATE
RFC-0013             RFC-400        Architecture KEEP (rename)
RFC-0015 + RFC-0019 + RFC-0022  RFC-401  Impl Interface MERGE
RFC-0003             RFC-500        Architecture KEEP (rename)
RFC-0020 + RFC-0024  RFC-501        Impl Interface MERGE
RFC-0018             RFC-600        Architecture KEEP (rename)
RFC-0004 + RFC-0005 + RFC-0021  RFC-601  Architecture MERGE
─────────────────────────────────────────────────────────────
Total: 23 → 14 RFCs
```

---

## 8. Reference Documents (Non-RFC)

Files that remain as supporting documents, not RFCs:

| Document | Purpose | Reason |
|----------|---------|--------|
| `event-catalog.md` | Event type registry | Lookup table, updated frequently |
| `rest-api-spec.md` | HTTP REST API reference | API consumer reference |
| `rfc-standard.md` | RFC writing conventions | Meta-document |
| `rfc-history.md` | Change log | Meta-document |
| `rfc-namings.md` | Terminology glossary | Lookup table |

---

## 9. Implementation Steps

### Phase 1: Preparation
1. Create migration tracking spreadsheet or markdown table
2. Backup current `docs/specs/` directory
3. Update `rfc-index.md` with planned changes (draft mode)

### Phase 2: Create New RFCs
1. Create RFC-301 (Protocol Registry) — new document
2. For each merge target, combine source RFCs into single document
3. Apply appropriate kind template (Conceptual/Architecture/Impl Interface)
4. Update metadata (status, depends on, supersedes)

### Phase 3: Rename Existing RFCs
1. Rename kept RFCs to new numbering (0001 → RFC-000, etc.)
2. Update cross-references within each RFC
3. Update CLAUDE.md references

### Phase 4: Cleanup
1. Remove merged source RFCs from directory
2. Update `rfc-index.md` to final state
3. Update `rfc-history.md` with migration record
4. Verify all cross-references resolve

### Phase 5: Validation
1. Run `specs-refine` to validate consistency
2. Check all RFCs under 600 lines target
3. Verify kind alignment (sections match kind template)

---

## 10. Size Targets

| Kind | Target Lines | Max Lines |
|------|--------------|-----------|
| Conceptual Design | 300-500 | 600 |
| Architecture Design | 400-600 | 700 |
| Impl Interface Design | 400-600 | 700 |

All consolidated RFCs should stay under target. If exceeding, consider splitting by sub-topic.

---

## 11. Open Questions

1. **RFC-301 Protocol Registry** — Should this be Impl Interface or Architecture? (Proposed: Impl Interface, since it defines contracts)
2. **Naming convention** — Should files use `RFC-000.md` or `RFC-000-system-design.md`? (Proposed: keep semantic name suffix for readability)
3. **Dependency updates** — How to handle Depends on field during migration? (Proposed: update to new numbers in single pass)

---

## 12. Conclusion

This reclassification establishes a sustainable RFC organization that:

* Groups related specifications by domain prefix
* Balances consolidation (fluency) with separation (distinct concerns)
* Aligns each RFC with Platonic Coding kind templates
* Provides room for future growth without renumbering

The migration from 23 to 14 RFCs reduces fragmentation while preserving all essential specification content.

> **14 well-organized RFCs beat 23 scattered ones.**