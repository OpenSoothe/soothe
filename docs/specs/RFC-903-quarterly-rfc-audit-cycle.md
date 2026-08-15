# RFC-903: Quarterly RFC Audit Cycle

**RFC**: 903
**Title**: Quarterly RFC Audit Cycle
**Status**: Proposed
**Kind**: Process Specification
**Created**: 2026-08-11
**Authors**: Soothe Team
**Dependencies**: RFC-900 (Deprecation List and Number Segment Reclassification Scheme)

## Abstract

This RFC establishes a recurring quarterly audit cycle for the Soothe RFC
corpus. Each cycle produces a structured assessment of RFC health: lifecycle
status accuracy, spec-vs-codebase drift, dependency graph integrity, DAG
boundary compliance, deprecation backlog throughput, and index/catalog
hygiene. The cycle's output is a published audit report plus a prioritized
remediation backlog (RFC status changes, archive candidates, drift fixes)
fed into the next quarter's IG work.

This is a **Process Specification**: it defines cadence, roles, scope, and
tracking metrics — not runtime architecture or API contracts.

## Motivation

### Current Problems

1. **Status Drift Without Cadence**
   RFC-900 introduced a formal lifecycle (`Draft → Proposed → Accepted →
   Implemented → Deprecated → Archived`) and a deprecation process, but no
   recurring cadence enforces it. As of 2026-08-11, the index shows 58 of 90
   RFCs in `Draft` — many almost certainly stale or silently implemented — and
   `rfc-history.md`'s total (85) disagrees with `rfc-index.md`'s total (90).
   Without a scheduled audit, these inconsistencies accumulate.

2. **Spec-vs-Code Drift Detected Reactively, Not Periodically**
   The TJL pipeline (`docs/analysis/ci-rfc-boundary-report.md`) already
   computes DAG boundary violations, declared path mismatches, API contract
   mismatches, and declared-but-unimplemented components. But it runs on
   demand. The 2026-08-11 snapshot showed 0 DAG violations (healthy) but 17
   path mismatches, 10 contract mismatches, and 12 declared-but-unimplemented
   components — drift that grew silently between audits.

3. **Deprecation Backlog Has No Throughput Target**
   RFC-900 mandates a 90-day Deprecated → Archived window, but nothing
   checks that the window is honored. The 2026-07 path-restructure notice in
   `rfc-index.md` flags that many RFCs retain design-time paths that no longer
   match the codebase — a known, unbounded drift surface.

4. **No Tracked Health Metrics Over Time**
   There is no time series of corpus health. Decisions about whether to
   consolidate series, retire a sub-category, or invest in spec completion
   are made without trend data.

### Why Quarterly

- The 90-day Deprecated → Archived window aligns naturally with a quarterly
  cadence: each cycle can close out deprecation windows that matured during
  it.
- RFC lifecycle transitions (Proposed ≤30 days, Accepted ≤90 days) fit inside
  a quarter, so each audit can verify time-box compliance.
- Quarterly is frequent enough to catch drift before it compounds, but not so
  frequent that auditing overhead dominates.

## Guiding Principles

1. **Audit is non-destructive.** The audit reports state and recommends; it
   does not unilaterally change RFC status. Status transitions follow the
   RFC-900 process (supersession notice → dependency update → index update →
   archive timeline).
2. **Reuse existing tooling.** The audit consumes the TJL pipeline outputs
   (`tjl-02-codebase-index.json`, `tjl-05-rfc-vs-codebase-diff-report.json`,
   `ci-rfc-boundary-report.md`) rather than re-deriving them. It does not
   duplicate AST or import-graph work.
3. **Metrics are comparable across cycles.** Each report uses the same metric
   definitions so quarter-over-quarter trends are meaningful.
4. **Process specs are in scope too.** This RFC and RFC-900 are themselves
   audited for fitness (the audit is self-applying).
5. **Internal-only identifiers.** Per AGENTS.md §7, no IG-/RFC- identifiers
   appear in user-visible runtime strings. Audit reports are internal
   documentation; they may freely reference RFC-XXX.

## Scope

### In Scope

| Concern | Audited Against |
|---------|-----------------|
| RFC lifecycle status accuracy | Actual codebase state + `rfc-index.md` |
| Spec-vs-codebase drift | TJL-05 diff report (paths, contracts, declared-but-unimplemented) |
| DAG boundary compliance | TJL-05 DAG violation count + `scripts/check_module_import_boundaries.sh` |
| Dependency graph integrity | RFC `Dependencies` / `Supersedes` headers vs actual references |
| Deprecation backlog throughput | RFC-90 Deprecated → Archived window compliance |
| Index/catalog hygiene | `rfc-index.md` totals, `rfc-history.md` totals, `rfc-namings.md` term coverage |
| Series/sub-category coherence | RFC-900 series semantics; overcrowding (e.g., 2xx at 22 RFCs) |
| Path-restructure drift | `rfc-index.md` path-mapping table vs current codebase layout |

### Out of Scope

- Implementation of any RFC (that is IG work).
- Runtime behavior changes.
- Re-deriving the codebase module graph or import edges (TJL pipeline owns this).
- User-visible CLI/daemon/config string review (covered by IG-709-style audits,
  not the corpus audit).

## Cadence

### Schedule

The cycle runs once per calendar quarter, anchored to the start of each
quarter. Anchoring avoids drift in audit timing.

| Cycle | Window | Audit Week | Report Published By |
|-------|--------|------------|---------------------|
| Q1 | Jan–Mar | Week 2 of Mar | Mar 15 |
| Q2 | Apr–Jun | Week 2 of Jun | Jun 15 |
| Q3 | Jul–Sep | Week 2 of Sep | Sep 15 |
| Q4 | Oct–Dec | Week 2 of Dec | Dec 15 |

> The first cycle under this charter runs **Q3 2026**, with the report
> published by 2026-09-15. (The 2026-08-11 TJL snapshot serves as the
> baseline.)

### Cycle Phases

Each quarterly cycle has four phases, scoped to fit inside audit week plus
a short follow-up:

```
Phase 1: Collect   → Phase 2: Assess   → Phase 3: Recommend   → Phase 4: Publish
 (1 day)              (1–2 days)          (1 day)               (1 day)
```

#### Phase 1 — Collect (Day 1)

Run (do not rewrite) the existing pipelines and gather the immutable inputs:

1. Re-run the TJL pipeline to refresh:
   - `docs/analysis/tjl-02-codebase-index.json`
   - `docs/analysis/tjl-05-rfc-vs-codebase-diff-report.json`
   - `docs/analysis/ci-rfc-boundary-report.md`
2. Run `./scripts/check_module_import_boundaries.sh` (owned-package DAG).
3. Snapshot `docs/specs/rfc-index.md`, `docs/specs/rfc-history.md`,
   `docs/specs/rfc-namings.md` current `Last Updated` and totals.
4. Enumerate all RFC files under `docs/specs/` and `docs/specs/archive/`.
5. Record the cycle baseline timestamp.

No analysis in this phase — only collection. Inputs are frozen for the cycle.

#### Phase 2 — Assess (Days 2–3)

Evaluate each scope concern against collected inputs. For every RFC, classify
into one audit verdict:

| Verdict | Meaning | Action |
|---------|---------|--------|
| **Healthy** | Status accurate, paths resolve, deps consistent | None |
| **Drift — Low** | Path mismatch or stale reference; no semantic impact | Patch in-cycle (header/path fix) |
| **Drift — High** | Declared-but-unimplemented, contract mismatch, wrong status | IG backlog item |
| **Deprecation Due** | In Deprecated status ≥90 days | Archive per RFC-900 |
| **Series Overcrowded** | Sub-category exceeds coherence threshold | Consolidation proposal |
| **Orphaned** | No inbound references, not implemented, not archived | Archive candidate |

#### Phase 3 — Recommend (Day 4)

Produce the prioritized remediation backlog:

1. **Immediate (in-cycle)**: header/path/reference fixes that do not change
   semantics. Apply directly and re-run `./scripts/verify_finally.sh`.
2. **Next-quarter IG backlog**: drift-high items, declared-but-unimplemented
   components, contract mismatches. Each becomes a stub IG entry or a note on
   an existing IG.
3. **Status transitions**: RFC-900-compliant deprecation/archival proposals,
   each with supersession notice and archive date.
4. **Series consolidation proposals**: only when overcrowding exceeds the
   threshold (see Metrics).

#### Phase 4 — Publish (Day 5)

1. Write the report to `docs/analysis/rfc-audit-QYYYY.md` (e.g.,
   `rfc-audit-Q3-2026.md`).
2. Update `rfc-index.md` and `rfc-history.md` `Last Updated` and totals to
   reflect in-cycle changes.
3. Append a summary entry to `rfc-history.md` under a new dated section.
4. File remediation backlog items (IG stubs or tracking issues).

## Roles

> This is a small corpus maintained by a small team. Roles are
> responsibility hats, not headcount additions.

| Role | Responsibility |
|------|----------------|
| **Audit Owner** | Runs the cycle end-to-end; signs off on the report; the single accountable party for a given quarter |
| **Collector** | Runs Phase 1 pipelines; may be the same person as Audit Owner |
| **Reviewers** | At least one reviewer other than the Audit Owner signs off on status-transition recommendations before they are applied |
| **IG Owners** | Receive the next-quarter backlog; acknowledge or reassign during their normal IG planning |

The Audit Owner rotates each quarter to avoid single-point bias and to spread
corpus familiarity. Rotation is recorded in each report.

## Tracking Metrics

All metrics are computed per cycle and recorded in the report's Metrics table
so trends are comparable across quarters.

### Corpus Health Metrics

| Metric | Definition | Target / Threshold |
|--------|------------|-------------------|
| **Total RFCs (active)** | Count of non-archived RFCs in `docs/specs/` | Tracked (no fixed target) |
| **Total RFCs (archived)** | Count in `docs/specs/archive/` | Tracked |
| **Index vs history total delta** | `rfc-index.md` total − `rfc-history.md` total | **0** (any nonzero is a hygiene bug) |
| **Draft ratio** | `Draft` count ÷ active total | Trend down quarter-over-quarter |
| **Implemented ratio** | `Implemented` count ÷ active total | Trend up |
| **Status accuracy rate** | RFCs whose declared status matches assessed reality ÷ active total | ≥ 95% |
| **Deprecation window compliance** | Deprecated RFCs archived within 90 days ÷ those due | 100% |
| **Orphan count** | RFCs classified Orphaned | Trend toward 0 |

### Spec-vs-Code Drift Metrics

Sourced from TJL-05 / `ci-rfc-boundary-report.md`:

| Metric | Definition | Target |
|--------|------------|--------|
| **DAG boundary violations** | Cross-package import edges violating §7b DAG | **0** (hard) |
| **Declared path mismatches** | RFC-declared paths not found in codebase | Trend down; zero net-new per quarter |
| **API contract mismatches** | Declared signatures absent in code | Trend down |
| **Declared-but-unimplemented** | RFCs/sections with no code realization | Tracked; each item has an IG or an archive decision |
| **Data models verified** | Declared data models found in code ÷ declared | Trend up |

### Dependency Graph Metrics

| Metric | Definition | Target |
|--------|------------|--------|
| **Dangling dependency references** | RFC `Dependencies`/`Supersedes` pointing at non-existent or wrong RFC | 0 |
| **Missing reverse references** | RFC A depends on B, but B doesn't note A where required | 0 |
| **Path-restructure drift** | RFCs still using pre-2026-07 `core/` paths not covered by the index mapping table | Trend toward 0 |

### Series Coherence Metrics

Per RFC-900 series semantics:

| Metric | Definition | Threshold for Consolidation Proposal |
|--------|------------|--------------------------------------|
| **Series size** | RFC count per series (0xx–9xx) | Any series > 25 triggers a consolidation review |
| **Sub-category spread** | Distinct sub-categories used per series | Tracked |
| **Cross-series leakage** | RFCs whose topic fits another series' scope | 0 |

### Process Fitness Metrics (self-audit)

| Metric | Definition | Target |
|--------|------------|--------|
| **Cycle on-time delivery** | Report published by cycle deadline | 100% |
| **In-cycle verify green** | `./scripts/verify_finally.sh` passes after in-cycle fixes | 100% |
| **Backlog burn rate** | Next-quarter IG items closed by next audit ÷ items opened | Trend up |
| **Audit reuse of TJL** | Audit did not re-derive AST/import graph independently | 100% |

### Trend Recording

Each report includes a compact trend table comparing the current cycle to the
prior cycle and the baseline (Q3 2026). Example shape:

| Metric | Baseline (Q3 2026) | Prior Cycle | This Cycle | Δ |
|--------|--------------------|-------------|------------|---|
| DAG boundary violations | 0 | — | 0 | 0 |
| Declared path mismatches | 17 | — | _n_ | _n − 17_ |
| Index vs history delta | 5 | — | _n_ | _n − 5_ |
| Draft ratio | 58/90 ≈ 64% | — | _n_ | _…_ |

## Inputs and Artifacts

### Inputs (per cycle, frozen at Phase 1)

- `docs/analysis/tjl-02-codebase-index.json`
- `docs/analysis/tjl-05-rfc-vs-codebase-diff-report.json`
- `docs/analysis/ci-rfc-boundary-report.md`
- `docs/specs/rfc-index.md` (snapshot)
- `docs/specs/rfc-history.md` (snapshot)
- `docs/specs/rfc-namings.md` (snapshot)
- `docs/specs/` and `docs/specs/archive/` file listings
- `./scripts/check_module_import_boundaries.sh` output

### Artifacts (produced per cycle)

- `docs/analysis/rfc-audit-QYYYY.md` — the report
- Updated `rfc-index.md` / `rfc-history.md` (in-cycle changes only)
- IG stubs or tracking entries for next-quarter backlog
- Optional: series consolidation proposal (only if threshold breached)

## Relationship to Existing Process

| Existing | Relationship |
|----------|--------------|
| RFC-900 (Deprecation scheme) | This cycle *operationalizes* RFC-900's 90-day archive window and lifecycle transitions on a schedule. |
| RFC lifecycle in `rfc-standard.md` | This cycle *verifies* lifecycle compliance; it does not redefine states. |
| TJL pipeline (`docs/analysis/`) | This cycle *consumes* TJL outputs; it never re-derives the module graph. |
| `scripts/check_module_import_boundaries.sh` | This cycle *runs* it and records the result; the script's verdict is authoritative for DAG compliance. |
| IG process (`docs/impl/`) | This cycle *feeds* the IG backlog with drift-high items; it does not write IGs. |
| AGENTS.md §7b (Package Boundaries) | The DAG compliance metric is a direct measurement of §7b. |
| AGENTS.md §6 (Cleanse → Verify → Fix) | In-cycle fixes follow the §6 sequence; the audit does not bypass verify. |

## Non-Goals

- This RFC does **not** change the RFC lifecycle model. That is RFC-900 and
  `rfc-standard.md`.
- This RFC does **not** introduce a new tool or pipeline. It schedules and
  consumes existing ones.
- This RFC does **not** make status decisions unilaterally. Recommendations
  require reviewer sign-off (see Roles) and follow RFC-900 transitions.
- This RFC does **not** prescribe headcount or a standing committee. It
  prescribes a cadence and responsibilities.

## Open Questions

1. **Automation of cadence trigger.** ~~Should the audit be triggered by a
   cron entry (RFC-229 cron service) or remain a calendar-driven manual
   start? Proposal: start manual for the first two cycles (Q3, Q4 2026),
   then evaluate cron-triggered Phase 1 collection if the manual cadence
   holds.~~ **Resolved (2026-08-11):** Phase 1 (Collect) automation is
   intended to run quarterly (anchored to the 15th of Mar/Jun/Sep/Dec per
   §Cadence). The automation runs the TJL pipeline and import-boundary scan,
   uploads frozen inputs as artifacts, opens an audit reminder issue for the
   Audit Owner, and is non-destructive (never changes RFC status). Phases 2–4
   remain human-driven per §Roles.
2. **Archive-vs-deprecate auto-promotion.** Should the audit auto-archive
   RFCs whose 90-day window has elapsed, or only *recommend* archival?
   Proposal: recommend only; archival is a status transition requiring
   reviewer sign-off per Roles.
3. **Series consolidation cadence.** Should consolidation proposals be
   annual rather than per-quarter to avoid churn? Proposal: per-quarter
   proposals, but implementation (renumbering) batched annually.

## Baseline Snapshot (Q3 2026, pre-cycle)

Recorded from the 2026-08-11 TJL run and index snapshots; serves as the
against-which trend baseline for all future cycles:

| Metric | Baseline Value |
|--------|----------------|
| Total RFCs (index) | 90 |
| Total RFCs (history) | 85 |
| Index vs history delta | 5 |
| Draft | 58 |
| Implemented | 18 |
| Archived | 9 |
| Proposed | 2 |
| Accepted | 1 |
| DAG boundary violations | 0 |
| Declared path mismatches | 17 |
| API contract mismatches | 10 |
| Declared-but-unimplemented | 12 |
| Data models verified | 8/21 |
| Codebase modules indexed | 1309 |
| Codebase internal edges | 2272 |

## Review and Revision of This Charter

This RFC is itself subject to the quarterly audit (per "process specs are in
scope too"). After the first two cycles (Q3 and Q4 2026), the Audit Owner
should propose revisions to cadence, metrics, or thresholds based on what the
trend data reveals. Material changes follow the standard RFC lifecycle
(Proposed → Accepted).
