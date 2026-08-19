# RFC Methodology Guide

> Synthesized from RFC-900 (lifecycle/reclassification), the RFC template,
> `rfc-namings.md`, `rfc-index.md`, and IG-744 (gap/drift report).
>
> This guide is a **reusable playbook**: it distills the methodology scattered
> across governance RFCs and implementation guides into a single reference.
> It is normative for new RFC authoring and gap-triage work.

**Created**: 2026-08-14
**Synthesis source**: TEE-01 audit (full RFC/refinement corpus scan)

---

## Table of Contents

1. [RFC Lifecycle](#1-rfc-lifecycle)
2. [Authoring an RFC](#2-authoring-an-rfc)
3. [RFC Kinds and When to Use Each](#3-rfc-kinds-and-when-to-use-each)
4. [Number Segments](#4-number-segments)
5. [Terminology Discipline](#5-terminology-discipline)
6. [Index and Catalog Hygiene](#6-index-and-catalog-hygiene)
7. [Dependency Tracking](#7-dependency-tracking)
8. [Deprecation and Archival](#8-deprecation-and-archival)
9. [Path-Restructure Drift Management](#9-path-restructure-drift-management)
10. [Spec-vs-Code Gap Inventory Method](#10-spec-vs-code-gap-inventory-method)
11. [Gap Triage: Criticality × Impact](#11-gap-triage-criticality--impact)
12. [Series Consolidation Triggers](#12-series-consolidation-triggers)
13. [Checklists](#13-checklists)

---

## 1. RFC Lifecycle

RFC-900 defines a formal six-state lifecycle (plus Rejected). Every RFC must
carry a `Status:` header matching one of these states:

```
Draft → Proposed → Accepted → Implemented → Deprecated → Archived
                    ↓
                 Rejected
```

| Status        | Definition                                          | Duration        |
|---------------|-----------------------------------------------------|-----------------|
| **Draft**     | Initial design; not ready for implementation review | Indefinite      |
| **Proposed**  | Ready for review, seeking approval                  | ≤ 30 days       |
| **Accepted**  | Approved for implementation; not yet started        | ≤ 90 days       |
| **Implemented** | Fully implemented in codebase                      | Until superseded |
| **Deprecated** | Superseded; retained for historical reference      | Min. 90 days    |
| **Archived**  | Removed from active index; moved to archive dir     | Permanent        |
| **Rejected**  | Not approved                                        | Permanent        |

**Rules:**

- The bare token `Implemented (partial)` is **not** a sanctioned lifecycle
  state. Use `Implemented` with partial-implementation prose in the body, or
  `Draft` if the core contract is unshipped.
- Time-box compliance (Proposed ≤ 30d, Accepted ≤ 90d) is checked during
  routine status reviews.
- Status transitions are **non-destructive**: a review recommends; status
  changes follow the RFC-900 supersession process (§8 below).

---

## 2. Authoring an RFC

### 2.1 Use the Template

Copy `docs/specs/templates/rfc-template.md`. The template provides three
section variants (see §3). Required header fields:

```markdown
**RFC**: RFC-XXXX
**Title**: [Descriptive Title]
**Status**: Draft | Proposed | Accepted | Implemented | Deprecated
**Kind**: Conceptual Design | Architecture Design | Implementation Interface Design
**Created**: YYYY-MM-DD
**Dependencies**: RFC-XXXX, RFC-XXXX
```

### 2.2 File Naming

```
docs/specs/RFC-{number}-{kebab-case-title}.md
```

Example: `RFC-630-start-phase-llm-intake-branch-routing.md`

### 2.3 Required Sections (all kinds)

- **Overview** — high-level summary
- **Motivation** — what problem this solves; current problems if refining
- **Guiding Principles** — design principles that guided the RFC

### 2.4 Kind-Specific Sections

See §3 for which variant applies.

### 2.5 Post-Authoring Updates

When an RFC is created or its status changes:

1. Add/update entry in `docs/specs/rfc-index.md` catalog section
2. Add entry in `docs/specs/rfc-history.md` (chronological log)
3. Register any new terms in `docs/specs/rfc-namings.md`
4. If implementation guide exists, cross-link from RFC body

**Failure to update index and history in lockstep is a hard hygiene bug**
(see §6). A prior corpus scan found a +5 delta between these files.

---

## 3. RFC Kinds and When to Use Each

The template supports three kinds. Choose based on the RFC's purpose:

| Kind | When to use | Template sections |
|------|-------------|-------------------|
| **Conceptual Design** | Defining core abstractions, terminology, invariants | Core Abstractions, Terminology, System Invariants |
| **Architecture Design** | Component structure, responsibilities, data flow, constraints | Component Overview, Responsibilities, Data Flow, Architectural Constraints, Abstract Schemas |
| **Implementation Interface Design** | Concrete types, API contracts, method signatures | Type Definitions, API Contracts, Naming Conventions, Error Handling |

Additional ad-hoc kinds in the corpus (not in template but present):
- **Process Specification** (RFC-900) — lifecycle, roles, deprecation process
- **Protocol Specification** — Python `Protocol`/ABC interface definitions
- **Feature Enhancement** — incremental changes to existing RFCs

**Guidance**: Prefer the three template kinds. Use ad-hoc kinds sparingly and
document why the template kinds are insufficient.

---

## 4. Number Segments

RFC-900 established semantic number segments. New RFCs must be placed in the
correct segment:

| Segment | Domain | Current count |
|---------|--------|----------------|
| 0xx | Foundation (system concept, core protocols) | 2 |
| 1xx | CoreAgent runtime, tools, security | 6 |
| 2xx | StrangeLoop (plan-execute-assess loop) | 23 |
| 3xx | Protocols (planner, policy, durability, vector, identity) | 7 |
| 4xx | Events, display, comms, MCP | 7 |
| 5xx | CLI / TUI | 5 |
| 6xx | Refinements (agents, persistence, security, UX) | 25 |
| 8xx | Persistence backends | 3 |
| 9xx | Governance / process | 4 |

**Consolidation triggers** fire at ≥ 20 RFCs in a segment (see §14).

---

## 5. Terminology Discipline

Per AGENTS.md §7 and `rfc-namings.md`:

1. **Use concrete module names** (CoreAgent, StrangeLoop, GoalEngine) — never
   "layer N" abstraction.
2. **Never expose IG-XXX/RFC-XXX in user-visible strings** (logs, CLI output,
   errors, config descriptions). RFC identifiers are internal-only.
3. **Register new terms** in `docs/specs/rfc-namings.md` with definition and
   "Introduced In" RFC number.
4. **No keyword heuristics** (AGENTS.md §9 / RFC-630): prefer structured
   light-LLM fields or declarative config rules over keyword/regex content
   judgment. Structural controls (checkpoint gates, status vocabulary) may use
   deterministic rules.

---

## 6. Index and Catalog Hygiene

Two files must agree on total RFC count:

- `docs/specs/rfc-index.md` — catalog with status summary table
- `docs/specs/rfc-history.md` — chronological evolution log

**Hard rule:** Index total − History total must equal **0**.
Any nonzero delta is a hygiene bug.

### Updating the index

The index `RFC Status Summary` table must be regenerated from a full-corpus
`Status:` header scan whenever statuses change. A full-corpus scan found this
table stale by +16 Draft / −20 Implemented because it was not refreshed after
the 2026-06-19 RFC-900 reclassification.

### Updating the history

Append a one-line entry per RFC creation/status change. The history file's
`Total RFCs` header must match the index.

---

## 7. Dependency Tracking

Every RFC header should declare:

- **Dependencies**: RFCs this RFC depends on (prerequisites)
- **Supersedes**: RFCs this RFC replaces (if any)

### Dependency graph integrity check

Cross-reference `Dependencies`/`Supersedes` headers against the actual RFC
set. Dangling references (pointing to non-existent or archived RFCs) are a
finding. A routine `grep` across RFC headers verifies this.

---

## 8. Deprecation and Archival

RFC-900 defines a four-step deprecation process:

```
1. Supersession Notice   → Add "Superseded by: RFC-XXX" to deprecated RFC header
2. Dependency Update      → Update all RFCs that reference the deprecated RFC
3. Index Update          → Move from active to deprecated section in rfc-index.md
4. Archive Timeline      → After 90 days in Deprecated status, move to docs/archive/specs/
```

### Archived RFC status

Archived RFCs should carry `Status: Archived` in their header.

### Deprecation window compliance

RFC-900 mandates a minimum 90-day Deprecated → Archived window.

---

## 9. Path-Restructure Drift Management

RFCs written before the 2026-07 `core/` → flat package restructure contain
file paths that no longer match the codebase. The canonical path mappings are
maintained in `rfc-index.md` (Path Restructure Notice table).

### Management approach

- **Explicitly patched RFCs**: paths corrected inline; noted in the RFC file
- **Unpatched RFCs**: retain original design-time paths as historical context
- **Canonical mapping**: refer to the index's path-mapping table for current
  locations

---

## 10. Spec-vs-Code Gap Inventory Method

Derived from IG-spec-vs-code-gap-inventory. This is the **reusable procedure**
for cross-referencing RFCs against the codebase.

### Procedure

```
Step 1: EXTRACT
  For each RFC in docs/specs/ and docs/archive/specs/:
    - Extract title, status, and ## section headings
    - Identify the primary class/module/function named in the spec

Step 2: SEARCH
  For each RFC's primary component:
    - Run targeted rg -l "<component>" against packages/ (source only,
      excluding tests/)
    - Record: hit file paths or "zero hits"

Step 3: CLASSIFY
  Cross-reference search results against the RFC's Status: line:
    - Implemented       → RFC Status: Implemented + code evidence present
    - SNI               → RFC describes a component with no code evidence (pure gap)
    - IND               → code present but no RFC or RFC still Draft/Proposed (drift)
    - Partial / drift   → code exists but RFC status or design diverges

Step 4: DOCUMENT
  Produce inventory with four sections:
    A. Implemented RFCs (spec ↔ code aligned)
    B. Specified but Not Implemented (SNI) — pure gaps
    C. Implemented, Not Documented (IND) — code without RFC
    D. Status drift — mismatch between Status: line and reality
```

### Search scope

- **In scope**: `packages/{soothe, soothe-daemon, soothe-cli}/src/` (source
  only, excluding `tests/`)
- **Also check**: installed PyPI packages (`soothe`, `soothe_nano`,
  `soothe_sdk`) — components may live in PyPI deps, not the monorepo
- **Out of scope**: `client/*` submodules (consumed as code, not owned)

### Key lesson from IG-744

A component declared in an RFC status line may exist in a **different package**
than claimed. Always verify against both workspace source AND installed PyPI
packages. Example: `ProgressiveMCPRegistry` was claimed in `soothe.mcp` but
actually lives in `soothe_nano.mcp.mcp_progressive` (correct per DAG rules).

---

## 11. Gap Triage: Criticality × Impact

Derived from IG-gap-criticality-impact-criteria. Every gap row in the
inventory is scored on two axes, then mapped to a priority.

### Criticality criteria (C1–C6)

Criticality = *how severe is the absence*.

| ID | Criterion | Critical threshold | High threshold |
|----|-----------|-------------------|----------------|
| **C1** | Subsystem non-functional | Entire subsystem has no executable code path | Named component absent; subsystem runs degraded |
| **C2** | Blocks user-facing feature | CLI/TUI/API command surface entirely absent | Command surface partial; clunky substitute exists |
| **C3** | Blocks deployment/operator path | Gap prevents a documented deployment topology | Gap complicates but does not block deployment |
| **C4** | Core loop or security primitive absent | Foundational primitive has no implementation | Primitive exists piecemeal; unification absent |
| **C5** | Non-core / internal-only gap | — | Internal path where system runs without it |
| **C6** | Documentation / governance gap only | — | Missing RFC for shipped code (IND) or stale Status: line |

**Criticality levels (aggregate):**

- **Critical** — meets C1 **or** C2 **or** C3
- **High** — meets C4, not C1–C3
- **Medium** — meets C5 only
- **Low** — meets C6 only

### Impact criteria (I1–I5)

Impact = *how widely the gap is felt*. Highest applicable level wins.

| ID | Criterion | High | Medium | Low |
|----|-----------|------|--------|-----|
| **I1** | Blast radius across packages | ≥2 owned packages; blocks inter-package contract | One package's internal module | Single utility/helper |
| **I2** | Downstream dependency | ≥2 RFCs cite as prerequisite | 1 RFC depends on it | No RFC depends on it |
| **I3** | User/operator visibility | Directly observable by end users | Observable only via logs/config | Invisible at runtime |
| **I4** | Workaround availability | No workaround; feature unavailable | Workaround exists but clunky/undocumented | Trivial workaround or cosmetic |
| **I5** | Spec-debt vs code-debt direction | Code exists, spec missing (IND): high auditability impact | — | Spec exists, code missing (SNI): runtime impact dominates |

**Impact levels (aggregate):**

- **High** — High on I1 **or** I2 **or** I3 **and** I4-High (no workaround)
- **Medium** — Medium across the board, or High on I4 alone
- **Low** — Low across the board, or governance-only (I5 code-exists branch)

### Priority matrix (Criticality × Impact → P0–P3)

|  | Impact: High | Impact: Medium | Impact: Low |
|--|--------------|----------------|-------------|
| **Criticality: Critical** | **P0** | **P1** | P2¹ |
| **Criticality: High** | **P1** | **P2** | P3 |
| **Criticality: Medium** | **P2** | P3 | P3 |
| **Criticality: Low** | P2² | P3 | P3 |

**Priority bands:**

| Priority | Meaning | Remediation posture |
|----------|---------|---------------------|
| **P0** | Critical + High impact | Block release; schedule immediately |
| **P1** | Critical+Medium, or High+High | Schedule before next minor; security/deploy blockers |
| **P2** | Medium+High, High+Medium, governance+High | Backlog with intent; do not let grow |
| **P3** | Medium/Low remainder | Documentation/governance cleanup; opportunistic |

**Notes:**

1. ¹ A critical-but-low-impact gap is still P2: a non-functional subsystem (C1)
   with no downstream deps still needs triage before documentation work.
2. ² Governance gaps with high impact (shipped security-relevant module with
   no RFC) are P2: auditability risk precedes code work.

### Uplift rules

- **Security primitive absent** (C4) uplifts to Critical per criteria doc note.
- **≥2 RFCs depend on it** (I2-High) uplifts impact to High.
- Borderline cases resolved per §5 of the criteria doc.

### All criteria are structural/textual

Derived from spec text and the inventory's own code-evidence columns. No
keyword heuristics on user content (AGENTS §9 / RFC-630).

---

## 12. Series Consolidation Triggers

Series overcrowding is a governance concern.

| Trigger | Threshold | Action |
|---------|-----------|--------|
| Segment reaches ≥ 20 RFCs | **Consolidation threshold** | Trigger split/merge review |
| Segment reaches ≥ 25 RFCs | **At threshold** | Split review is mandatory; must propose consolidation RFC |

### Consolidation approach

When triggered, a governance review recommends:
1. Identify semantic sub-clusters within the segment
2. Propose splitting into new segments or merging overlapping RFCs
3. File a consolidation RFC (9xx governance series) with the reclassification
4. Execute via the RFC-900 deprecation/reclassification process

---

## 13. Checklists

### 13.1 New RFC Authoring Checklist

- [ ] Copied `docs/specs/templates/rfc-template.md`
- [ ] Header fields complete (RFC, Title, Status, Kind, Created, Dependencies)
- [ ] Correct number segment assigned (§4)
- [ ] Correct kind selected (§3); kind-specific sections filled
- [ ] No "layer N" terminology; concrete module names used (§5)
- [ ] No IG-/RFC- identifiers in any user-visible string context (§5)
- [ ] New terms registered in `rfc-namings.md` (§5)
- [ ] Entry added to `rfc-index.md` catalog (§6)
- [ ] Entry added to `rfc-history.md` (§6)
- [ ] Totals in index and history match (§6)
- [ ] Dependencies/Supersedes headers reference existing, non-archived RFCs (§7)
- [ ] File paths reflect current codebase layout (not pre-restructure paths) (§9)

### 13.2 Status Transition Checklist

- [ ] `Status:` header updated to new lifecycle state (§1)
- [ ] If Deprecated: supersession notice added (§8)
- [ ] If Deprecated: all RFCs referencing this RFC updated (§8)
- [ ] If Archived: moved to `docs/archive/specs/`; status set to `Archived` (§8)
- [ ] `rfc-index.md` Status Summary table regenerated from full-corpus scan (§6)
- [ ] `rfc-history.md` entry appended; totals match index (§6)

### 13.3 Gap Inventory Procedure Checklist

- [ ] Step 1: Extracted title, status, section headings from every RFC in `docs/specs/` and `docs/archive/specs/`
- [ ] Step 2: Ran targeted `rg -l "<component>"` against `packages/` source (excluding `tests/`)
- [ ] Step 2b: Also checked installed PyPI packages (`soothe`, `soothe_nano`, `soothe_sdk`)
- [ ] Step 3: Classified each as Implemented / SNI / IND / Partial-drift
- [ ] Step 4: Documented four sections (A: aligned, B: SNI gaps, C: IND gaps, D: status drift)
- [ ] Cross-referenced status claims against actual code evidence
- [ ] Flagged false implementation claims (status asserts code at path, code absent)
- [ ] Flagged status-understates-implementation (code shipped, status says Draft)
- [ ] Flagged wrong-package-location claims (code exists in different package than RFC states)

---

## Appendix: Document Map

| Document | Location | Role |
|----------|----------|------|
| RFC template | `docs/specs/templates/rfc-template.md` | Authoring scaffold |
| RFC index | `docs/specs/rfc-index.md` | Active catalog + status summary + path mappings |
| RFC history | `docs/specs/rfc-history.md` | Chronological evolution log |
| RFC namings | `docs/specs/rfc-namings.md` | Terminology registry |
| RFC-900 | `docs/specs/RFC-900-deprecation-reclassification-scheme.md` | Lifecycle model, deprecation process, reclassification |
| Gap inventory | `docs/impl/IG-spec-vs-code-gap-inventory.md` | Spec-vs-code cross-reference |
| Gap triage matrix | `docs/impl/IG-gap-triage-matrix.md` | Scored priorities (P0–P3) |
| Criticality criteria | `docs/impl/IG-gap-criticality-impact-criteria.md` | C1–C6 × I1–I5 scoring scheme |
| Gap/drift report | `docs/impl/IG-744-rfc-impl-gap-drift-report.md` | Verified gap/drift findings |
| IG template | `docs/specs/templates/impl-guide-template.md` | Implementation guide scaffold |
