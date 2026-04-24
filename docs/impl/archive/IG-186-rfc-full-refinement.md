# IG-186: Full RFC Refinement (Post-Consolidation Consistency)

**Date**: 2026-04-17  
**Status**: In Progress  
**Owner**: Codex

---

## Objective

Execute a full `specs-refine` consistency pass across `docs/specs/` to resolve numbering ambiguity, align status semantics, and standardize cross-references and index navigation after RFC consolidation work.

---

## Scope

- Normalize RFC identity consistency between filename and top-level RFC header.
- Standardize lifecycle status values where inconsistent with project RFC lifecycle.
- Reconcile index and consolidation documents to a single canonical model.
- Ensure legacy/alias guidance uses explicit file targets.
- Sweep high-risk cross-references for ambiguous number-only references.

Out of scope:
- Runtime code changes.
- Behavioral changes to implementation architecture.

---

## Canonical Decisions

1. Canonical merged RFCs remain short-name files:
   - `RFC-200.md`, `RFC-203-agentloop-state-memory.md`, `RFC-207-agentloop-thread-context-lifecycle.md`, `RFC-213-agentloop-reasoning-quality.md`
   - `RFC-400-context-protocol-architecture.md`, `RFC-402-memory-protocol-architecture.md`, `RFC-404-planner-protocol-architecture.md`, `RFC-406-policy-protocol-architecture.md`, `RFC-408-durability-protocol-architecture.md`, `RFC-410-remote-agent-protocol-architecture.md`
2. Legacy descriptive files are retained as historical/topic docs, but must avoid conflicting RFC identifiers in headers.
3. Daemon specs remain in `45x` filenames and must declare matching `45x` headers.
4. Cross-reference and index entries must prefer explicit file links when ambiguity is possible.

---

## Work Plan

1. Build inventory and mismatch report.
2. Write conflict-resolution ledger in working notes and fold final decisions into canonical spec docs.
3. Normalize headers/status metadata in affected RFC files.
4. Update legacy/alias navigation guidance.
5. Reconcile `rfc-index.md` and canonical RFC docs.
6. Sweep critical RFCs for ambiguous references and replace with explicit file links.
7. Validate consistency using targeted checks.

---

## Validation Checklist

- [ ] No filename/header RFC-number mismatches in active RFC files.
- [ ] Daemon files in `45x` range use matching `45x` headers.
- [ ] Consolidation/index/status docs reflect current file reality.
- [ ] Ambiguous references in high-risk RFCs replaced with explicit links.
- [ ] Lifecycle statuses use approved values (`Draft`, `Proposed`, `Accepted`, `Implemented`, `Deprecated`).

