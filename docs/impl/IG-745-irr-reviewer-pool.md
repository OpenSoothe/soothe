# Implementation Guide: IRR Reviewer Pool

**Guide**: IG-745
**Title**: Inter-Rater Reliability Reviewer Pool Implementation
**Created**: 2026-08-17
**Related RFCs**: RFC-904, RFC-903, RFC-900

## Overview

This implementation guide covers the creation of the inter-rater reliability
(IRR) reviewer pool config file (`config/irr_reviewer_pool.yml`) and the
integration of IRR calibration reporting into the quarterly RFC audit cycle
defined by RFC-903.

RFC-904 defines the schema, team structure, coverage rules, and calibration
scope. This IG specifies the concrete config file content, the calibration
reporting integration, and the verification steps.

## Prerequisites

- [x] RFC-904 authored (Proposed status)
- [x] RFC-903 accepted as the audit cycle charter
- [x] RFC-900 lifecycle statuses defined
- [x] Package DAG teams established (AGENTS.md §7b)

## Implementation Plan

### Phase 1: Config File Creation

**Goal**: Create the machine-readable reviewer pool with cross-team coverage.

**Tasks**:
- [x] Define the YAML schema inline in the config file (self-documenting)
- [x] Populate reviewer entries spanning all six package teams
- [x] Ensure DAG-level coverage (leaf + host)
- [x] Set calibration weights and expertise areas per reviewer

### Phase 2: Calibration Reporting Integration

**Goal**: Define how IRR metrics appear in the audit report.

**Tasks**:
- [x] Specify the "Inter-Rater Reliability" report section structure
- [x] Define the calibration corpus selection method
- [x] Document the kappa computation approach (deferred to tooling)

### Phase 3: Documentation

**Goal**: Update RFC index and history to include RFC-904.

**Tasks**:
- [x] Add RFC-904 entry to `docs/specs/rfc-index.md`
- [x] Add RFC-904 entry to `docs/specs/rfc-history.md`

## File Structure

```
config/
├── irr_reviewer_pool.yml          # NEW: reviewer pool config
├── soothe.template.yml             # existing host overlay
├── nano.template.yml              # existing nano config
└── daemon.template.yml            # existing daemon config

docs/specs/
└── RFC-904-inter-rater-reliability-reviewer-pool.md  # NEW: spec

docs/impl/
└── IG-745-irr-reviewer-pool.md    # NEW: this guide
```

## Implementation Details

### Config File

**File**: `config/irr_reviewer_pool.yml`

The config file is a single YAML document with three top-level keys:

1. `schema` — field definitions (self-documenting; mirrors RFC-904 §Reviewer Entry)
2. `teams` — the six-team DAG mapping (mirrors RFC-904 §Team Structure)
3. `reviewers` — the actual reviewer entries

See the committed file for the full content. The initial pool contains **8
reviewer entries** spanning all six teams:

| Team | Entries | DAG Level |
|------|---------|-----------|
| `sdk` | 1 | leaf |
| `nano` | 1 | leaf |
| `host` | 2 | host |
| `autopilot` | 2 | host |
| `daemon` | 1 | host |
| `cli` | 1 | host |

This satisfies RFC-904 §Coverage Rules: ≥3 distinct teams, both DAG levels
represented, and no team exceeds 25% of the pool (preventing single-team
dominance).

### Calibration Reporting Integration

The quarterly audit report (`docs/analysis/rfc-audit-<quarter>.md`) gains a
new section:

```markdown
## Inter-Rater Reliability

### Calibration Corpus
- Corpus size: N items
- Source: <primary audit flags + anchor RFCs>
- Reviewers: <list of reviewer IDs who rated>

### Agreement Metrics
| Reviewer Pair | Pairwise Agreement | Cohen's Kappa |
|---------------|-------------------|---------------|
| r-host-01 / r-autopilot-01 | 0.88 | 0.72 |
| ... | ... | ... |

| Multi-Rater | Fleiss' Kappa |
|-------------|---------------|
| All raters | 0.65 |

### Drift Delta
- Anchor agreement this cycle: 0.90
- Anchor agreement last cycle: N/A (first cycle)
- Drift delta: N/A
```

The kappa computation tooling is **not** implemented in this IG — it is
deferred to a future IG once the first calibration cycle produces real
rating data. The report section structure is defined now so the first cycle
has a target format.

## Testing Strategy

### Config Validation (Manual)

- [x] YAML parses without errors
- [x] All `team` values are in the defined six-team set
- [x] All `dag_level` values are `leaf` or `host`
- [x] No duplicate `id` values
- [x] No duplicate `display_name` values among active reviewers
- [x] Coverage rules satisfiable: ≥3 teams, both DAG levels present

### Unit Tests

No Python module is created in this IG — the config file is declarative.
Unit tests for config loading and coverage-rule enforcement are deferred to
a future IG that implements the reviewer-assignment tooling.

## Migration Notes

This is a new artifact; no migration is needed. The first audit cycle that
uses this pool will be the next quarterly cycle after RFC-904 reaches
Accepted status.

## Verification

- [x] Config file created at `config/irr_reviewer_pool.yml`
- [x] RFC-904 spec created at `docs/specs/RFC-904-inter-rater-reliability-reviewer-pool.md`
- [x] IG-745 created at `docs/impl/IG-745-irr-reviewer-pool.md`
- [x] RFC index updated
- [x] RFC history updated
- [x] All changes committed

## Related Documents

- [RFC-904: Inter-Rater Reliability Reviewer Pool](../specs/RFC-904-inter-rater-reliability-reviewer-pool.md)
- [RFC-903: Quarterly RFC Audit Cycle](../specs/RFC-903-quarterly-rfc-audit-cycle.md)
- [RFC-900: Deprecation and Reclassification Scheme](../specs/RFC-900-deprecation-reclassification-scheme.md)
- `config/irr_reviewer_pool.yml` — the pool config file
