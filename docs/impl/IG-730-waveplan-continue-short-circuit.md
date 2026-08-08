# IG-730: WavePlan continue short-circuit (plan_milestones)

**Created**: 2026-08-08  
**Status**: Implemented (+ cleanse)  
**Package**: `soothe`  
**Related**: [IG-722](IG-722-waveplan-multiform-transfer.md),
[IG-721](IG-721-waveplan-flat-semistructured-ingest.md),
[IG-704](IG-704-autopilot-wave-plan-host-ingest.md),
[RFC-232](../specs/RFC-232-waveplan-flat-semistructured-ingest.md)

---

## Goal

Stop greenfield/migration jobs from burning a long StrangeLoop planner turn when
a usable flat WavePlan is **already applied** (or present as a recommended dump)
at `job_start` — typical “Continue” / resume workspaces.

Incident pattern (job `a1b96ae5`): `rail_state.wave_slices` +
`wave_plan_source_path` + dumps existed at bind time, yet `plan_milestones`
still spawned a full architecture goal that rediscovered, rewrote, and wrote
markdown “validation/completion” reports for ~20+ minutes without completing.

## Design rules (MUST)

1. **SoT unchanged** — applied `RailJobState.wave_slices` / `decompose_plan`
   remain authoritative (IG-722).
2. **Host short-circuit** — when `plan_milestones` runs and a transfer dump (or
   recorded `wave_plan_source_path`) already makes `is_wave_plan_ready`, the
   host MUST:
   - create an architecture-tagged planner goal,
   - attach WavePlan findings JSON,
   - mark it completed,
   - invoke `spawn_wave_makers` in the same builtin call.
3. **No short-circuit on retry** — if any architecture/planner annotation
   already exists (including pruned failures), always spawn a normal planner
   goal so `retry_architecture` can force a fresh plan.
4. **No short-circuit on bare `wave_slices` seed** — pre-bound slices without
   dump/`wave_plan_source_path` do not trigger reuse (keeps unit harnesses and
   synthetic seeds honest).
5. **Brief efficiency** — planner copy tells agents: one-step verify +
   `wave_plan_path` / inline JSON; `independence` is a **string**; markdown
   reports are not deliverables.
6. **No IG/RFC ids** in user-visible briefs, logs, or errors.

## Work items

- [x] `RailBuiltinExecutor.invoke("plan_milestones")` ingest + reuse gate
- [x] `_plan_milestones_reuse_existing` → complete arch + `spawn_wave_makers`
- [x] Efficiency paragraph on default + greenfield/migration briefs
- [x] Unit tests: dump reuse; no-dump normal spawn; retry ignores dump
- [x] Related unit tests + ruff (full `verify_finally` blocked on mirror
      missing `soothe-nano>=1.1.6` for py3.14/win32 resolution — env, not this IG)

## Non-goals

- Changing `architecture_ready` guard semantics for in-flight planner goals
- Auto-accepting nested WavePlan / nested `independence` objects
- Skipping makers when `require_plan` and plan is missing

## Verification

- Unit: reuse path creates completed architecture + makers; root depends on makers
- Unit: empty workspace still gets pending planner
- Unit: `retry_architecture` after failed planner + dump on disk still spawns
  pending planner (no reuse)
- Manual: continue job with `.soothe/wave-plan.json` fans out without long
  planner loop

## Cleanse

- Efficiency copy is SoT in `verb_defaults.WAVEPLAN_EFFICIENCY_HINT` /
  `ensure_waveplan_efficiency_hint` (appended from recipe spawn +
  `resolve_verb_brief("plan_milestones")`); removed duplicate paragraphs from
  greenfield/migration YAML briefs.

## Notes

Peer greenfield planners without a pre-seeded dump still take ~15–20 minutes;
this IG only removes the **redundant** planner when transfer evidence already
satisfies the fan-out gate.
