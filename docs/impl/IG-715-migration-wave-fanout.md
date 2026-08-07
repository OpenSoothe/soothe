# IG-715: Migration greenfield-style waves + condition normalization

**Created**: 2026-08-07  
**Status**: Implemented  
**Related**: [IG-714](IG-714-architecture-wave-plan-accept-without-artifact.md),
[IG-704](IG-704-autopilot-wave-plan-host-ingest.md),
[IG-700](../archive/impl/IG-700-greenfield-fanout-closeout.md),
[RFC-230](../specs/RFC-230-job-maturity-assessment.md) (rail exclusivity),
[RFC-231](../specs/RFC-231-looprail-rail-exec.md) (Rail Exec — migrate planner
copy into YAML verb bodies; remove `rail_id` forks)

---

## Goal

1. Give the **`migration`** LoopRail the same job-scoped WavePlan / maker-wave
   fan-out as `greenfield-system` (`fanout:` + `plan_milestones` →
   `spawn_wave_makers` → integrate / commit / review / QA / feedback / next wave).
2. **Normalize** `ready_for_next_wave` to a single semantic (architecture /
   post-feedback wave advance). Remove the overloaded exploration-done path
   that migration previously shared under the same condition name.
3. Preserve migration-only **`needs_human` → `pause_for_user`** for irreversible
   cutover.

Engine remains wave-agnostic: waves exist only on rails that declare `fanout:`.

---

## Boundary (MUST)

| Layer | Owns | Must not |
|-------|------|----------|
| Autopilot engine | Pool, deps, consensus, schedule | Module names, `wave_index`, phase order |
| LoopRail YAML | `flow` / conditions / `fanout` contract | Submit kwargs for modules |
| LLM + job artifact | WavePlan modules for this job | Workspace `docs/wave-plan.json` SoT |

Rails with `fanout:` today: **`greenfield-system`**, **`migration`**.

---

## Design

### Migration v2.0 flow

Reuse greenfield builtins. Differences vs greenfield:

- Planner copy describes **migration slices** (schema / dual-write / cutover-prep),
  not product ownership units.
- Extra condition `needs_human` → `pause_for_user`.

### Condition normalization

- `ready_for_next_wave` structural short-circuit: architecture path only.
- Deleted: `not has_architecture` → `exploration_done` branch in guards.

### Planner text

Planner copy lives in rail YAML ``verbs.plan_milestones.brief`` (RFC-231 /
IG-716). Exec must not branch on ``rail_id``. Findings WavePlan JSON + host
ingest unchanged.

---

## Non-goals

- Wave/fanout on feature-dev, spike, hotfix, etc.
- Engine-level wave API.
- Workspace wave-plan scrape.

---

## Acceptance

1. Migration bind stamps `require_plan` / job-scoped artifact; makers need WavePlan.
2. `ready_for_next_wave` without architecture does not match structurally.
3. Migration still has `needs_human` → `pause_for_user`.
4. Verify green.
