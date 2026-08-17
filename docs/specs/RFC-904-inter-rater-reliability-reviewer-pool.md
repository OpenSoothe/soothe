# RFC-904: Inter-Rater Reliability Reviewer Pool

**RFC**: 904
**Title**: Inter-Rater Reliability Reviewer Pool
**Status**: Proposed
**Kind**: Process Specification
**Created**: 2026-08-17
**Authors**: Soothe Team
**Dependencies**: RFC-903 (Quarterly RFC Audit Cycle), RFC-900 (Deprecation and Reclassification Scheme)

## Abstract

This RFC establishes a structured inter-rater reliability (IRR) reviewer pool
for the Soothe quarterly RFC audit cycle (RFC-903). RFC-903 §Roles defines a
"Reviewers" responsibility hat requiring "at least one reviewer other than the
Audit Owner" to sign off on status-transition recommendations, but provides no
roster, no team coverage matrix, and no calibration mechanism. This RFC
defines the reviewer pool schema, cross-team team structure, calibration
scope, and the config file that holds the actual reviewer entries.

This is a **Process Specification**: it defines pool membership, team coverage,
calibration cadence, and reliability metrics — not runtime architecture or
API contracts.

## Motivation

### Current Problems

1. **Reviewer role is undefined in membership.** RFC-903 §Roles states
   "Reviewers: At least one reviewer other than the Audit Owner signs off on
   status-transition recommendations." This is a gating rule, not a pool. There
   is no roster of who the reviewers are, which teams they represent, or
   whether coverage is balanced across the package DAG.

2. **No inter-rater reliability measurement.** RFC-903 requires reviewer
   sign-off but does not measure whether reviewers agree. When two reviewers
   assess the same RFC's status (e.g., "Draft" vs "Implemented (partial)"),
   there is no kappa statistic, no agreement matrix, and no calibration corpus
   to detect rater drift.

3. **No cross-team coverage guarantee.** The Soothe monorepo spans six
   packages (`soothe-sdk`, `soothe-nano`, `soothe`, `soothe-autopilot`,
   `soothe-daemon`, `soothe-cli`) with a one-way dependency DAG. An audit
   recommendation touching `soothe-daemon` DAG boundaries should be reviewed by
   someone with daemon-team context, not only by a host-team reviewer.
   RFC-903 has no team-coverage requirement.

4. **Audit Owner rotation has no backup depth.** RFC-903 rotates the Audit
   Owner quarterly "to avoid single-point bias." Without a named pool, the
   rotation has no successor list and no guarantee the successor has prior
   calibration.

### Why a Pool Config (Not Inline in RFC-903)

- Reviewer membership changes over time (onboarding, offboarding, team
  reassignment). A config file is mutable; an RFC is versioned. Separating
  the schema (this RFC) from the entries (the config file) keeps the RFC
  stable while the pool evolves.
- The config file is machine-readable, enabling future tooling (automated
  reviewer assignment, coverage checks, kappa computation) without RFC
  rewrites.

## Guiding Principles

1. **Roles are hats, not headcount.** Consistent with RFC-903 §Roles,
   reviewer entries are role-based identities tied to package teams, not
   personal names. This avoids fabrication of real people while providing
   concrete, addressable reviewers.

2. **Cross-team coverage is mandatory.** Every audit cycle must draw reviewers
   from at least three distinct package teams, spanning at least two DAG
   levels (leaf and host), to prevent single-team bias.

3. **Calibration is periodic, not continuous.** A calibration corpus of
   double-rated RFC assessments is maintained and re-scored each quarter to
   detect rater drift. This is process calibration (measuring reviewer
   agreement), not model calibration.

4. **Config-driven, not code-driven.** The pool is a YAML config file under
   `config/`, not a Python module. This follows the Soothe convention of
   declarative configuration (cf. `soothe.template.yml`, rail YAML files).

5. **Internal-only identifiers.** Per AGENTS.md §7, no IG-/RFC- identifiers
   appear in user-visible runtime strings. The pool config and calibration
   reports are internal documentation; they may freely reference RFC-XXX.

## Scope

### In Scope

| Concern | Defined By This RFC |
|---------|---------------------|
| Reviewer pool schema | Field definitions, types, constraints |
| Team structure | Package-team mapping aligned to the DAG |
| Reviewer entries | The config file `config/irr_reviewer_pool.yml` |
| Calibration scope | What is calibrated, cadence, metric definitions |
| Coverage rules | Minimum team diversity per cycle |
| Pool governance | Onboarding, offboarding, rotation |

### Out of Scope

- Runtime enforcement code (automated reviewer assignment algorithms) — that
  is IG implementation work, not process spec.
- Personal identities of human reviewers — the pool uses role-based display
  names tied to teams.
- RFC-903 audit metric definitions (corpus health, spec-vs-code drift) —
  those remain owned by RFC-903. This RFC only adds reviewer-agreement
  metrics.

## Core Abstractions

### Reviewer Entry

A reviewer entry represents one reviewer hat in the pool. Each entry has:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Stable identifier (e.g., `r-autopilot-01`) |
| `display_name` | string | Role-based name (e.g., `"Autopilot Team Reviewer"`) |
| `team` | string | Package team (one of the six DAG teams) |
| `dag_level` | enum | `leaf` (sdk, nano) or `host` (soothe, autopilot, daemon, cli) |
| `expertise_areas` | list[string] | RFC series or domains (e.g., `["2xx", "7xx-rails"]`) |
| `calibration_weight` | float | Weight in calibration scoring (0.0–1.0; default 1.0) |
| `active` | bool | Whether the reviewer is eligible this cycle |
| `onboarded_cycle` | string | First cycle this reviewer was active (e.g., `"Q3-2026"`) |

### Team Structure

Teams map directly to the monorepo package DAG (AGENTS.md §7b):

| Team | DAG Level | Package | Reviewer Focus |
|------|-----------|---------|----------------|
| `sdk` | leaf | `soothe-sdk` | Shared contracts, wire, display, protocols |
| `nano` | leaf | `soothe-nano` | Coding CoreAgent, skills, MCP backends |
| `host` | host | `soothe` | StrangeLoop, Context Engine, identity, runner |
| `autopilot` | host | `soothe-autopilot` | Goal scheduling, dispatch, rails, verify |
| `daemon` | host | `soothe-daemon` | Process lifecycle, channels, cron, admin IO |
| `cli` | host | `soothe-cli` | Typer + Textual TUI, WebSocket transport |

### Calibration Scope

Calibration measures **reviewer agreement on RFC status-transition
recommendations** — the exact gate RFC-903 §Roles assigns to Reviewers.

**Calibration corpus**: A set of 8–12 RFC status assessments per cycle,
double-rated by two or more pool reviewers. The corpus is drawn from:

1. RFCs flagged for status transition in the current audit (primary source).
2. A rolling set of 3 "anchor" RFCs re-rated every cycle to detect drift
   (one stable Implemented, one Draft, one Deprecated/Archived).
3. Edge cases: RFCs with ambiguous status (e.g., "Implemented (partial)").

**Calibration metrics**:

| Metric | Definition | Target |
|--------|------------|--------|
| **Pairwise agreement rate** | Fraction of corpus items where two reviewers assign the same status | ≥ 0.80 |
| **Cohen's kappa** | Agreement corrected for chance (per reviewer pair) | ≥ 0.60 (substantial) |
| **Fleiss' kappa** | Multi-rater agreement (when ≥3 reviewers rate) | ≥ 0.60 |
| **Drift delta** | Anchor-item agreement this cycle minus last cycle | Trend toward 0 |

### Coverage Rules

Per audit cycle, reviewer assignment must satisfy:

1. **Minimum reviewers**: ≥ 2 active reviewers per status-transition batch.
2. **Cross-team diversity**: reviewers must span ≥ 3 distinct teams.
3. **DAG-level span**: at least one `leaf`-level and one `host`-level reviewer.
4. **No self-review**: the Audit Owner's team provides no reviewer for
   transitions the Audit Owner authored (prevents self-confirmation bias).

## System Invariants

1. **Pool config is the single source of truth.** The reviewer roster lives
   only in `config/irr_reviewer_pool.yml`. No parallel inline list in any
   RFC or code module.

2. **Every active reviewer has a team.** The `team` field is required and must
   be one of the six defined teams. No "general" or "unaffiliated" team.

3. **Calibration corpus is versioned.** The corpus and its ratings are
   recorded in the audit report (`docs/analysis/rfc-audit-<quarter>.md`) so
   trends are comparable across cycles, per RFC-903 §Tracking Metrics.

4. **Reviewer entries are role-based.** No personal names. Display names
   follow the pattern `"<Team> Team Reviewer"` or `"<Team> Team Reviewer (N)"`
   when multiple reviewers share a team.

## Pool Governance

### Onboarding

A new reviewer entry is added by appending to `config/irr_reviewer_pool.yml`
with `active: true` and `onboarded_cycle` set to the current cycle. The
display name must not collide with an existing active entry's display name.

### Offboarding

Set `active: false`. Do not delete the entry — historical calibration data
references reviewer IDs, and deletion would break audit-report traceability.

### Rotation

The Audit Owner role (RFC-903) rotates quarterly. The successor is selected
from active pool members whose `onboarded_cycle` is at least one cycle prior,
preferring members from a different team than the outgoing Audit Owner.

## Naming Conventions

- Reviewer IDs: `r-<team>-<NN>` (e.g., `r-autopilot-01`).
- Config file: `config/irr_reviewer_pool.yml`.
- Calibration data: embedded in `docs/analysis/rfc-audit-<quarter>.md`
  under a "## Inter-Rater Reliability" section (added by this RFC).

## Error Handling

- If the pool has fewer than 2 active reviewers: the audit cycle cannot
  proceed; the report records "IRR pool insufficient" as a blocker.
- If coverage rules cannot be satisfied (e.g., only 2 teams have active
  reviewers): the report records "coverage insufficient" and the cycle
  proceeds with a documented coverage gap rather than blocking entirely.

## Open Questions

1. Should calibration weight (`calibration_weight`) be used to weight kappa
   computations, or only for reviewer-selection priority? **Resolution
   deferred to first calibration cycle.**
2. Should anchor RFCs be fixed permanently or rotate every 4 quarters?
   **Default: fixed for the first year, then reviewed.**

## Related Documents

- [RFC-903: Quarterly RFC Audit Cycle](RFC-903-quarterly-rfc-audit-cycle.md)
  — defines the audit cycle this pool serves.
- [RFC-900: Deprecation and Reclassification Scheme](RFC-900-deprecation-reclassification-scheme.md)
  — defines the lifecycle statuses reviewers assess.
- `config/irr_reviewer_pool.yml` — the pool config file (schema defined here).
- [IG-745: IRR Reviewer Pool Implementation](../impl/IG-745-irr-reviewer-pool.md)
  — implementation guide for the config file and calibration tooling.
