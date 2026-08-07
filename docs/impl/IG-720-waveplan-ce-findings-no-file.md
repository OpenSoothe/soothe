# IG-720: WavePlan via CE findings only (remove file artifact)

**Created**: 2026-08-07  
**Status**: Implemented  
**Related**: [RFC-231](../specs/RFC-231-looprail-rail-exec.md) §9,
[IG-704](IG-704-autopilot-wave-plan-host-ingest.md),
[IG-714](IG-714-architecture-wave-plan-accept-without-artifact.md),
[IG-718](IG-718-fanout-slice-terminology.md)

---

## Goal

Make the architecture WavePlan **solely** a Context Engine completion artifact
(findings on the planner goal + applied `RailJobState`), and **delete** all
filesystem WavePlan JSON paths (`jobs/{id}/wave-plan.json`,
`fanout.artifact`, load/dump helpers).

Motivation: dual SoT (findings gate + host file) taught agents and operators to
write/seed files; production stalls when findings lack bare WavePlan JSON even
if workspace or orphan job files exist.

---

## Design rules (MUST)

1. **SoT**: `GoalCompletionChunk` contribution findings → `GoalNode.findings`
   → parse → `record_wave_plan` applies `wave_slices` / `decompose_plan` on
   `RailJobState` → persist `rail_state.json` only.
2. **No file I/O** for WavePlan: remove `dump_wave_plan`, `load_wave_plan`,
   path expand/normalize/resolve, `RailJobState.wave_plan_artifact`,
   `fanout.artifact` (catalog **reject** if present).
3. **`is_wave_plan_ready`**: non-empty `state.wave_slices`, else parse
   architecture goal findings in CE. Never probe disk.
4. **Orphans ignored**: leftover `$SOOTHE_DATA_DIR/jobs/*/wave-plan.json` are
   not read or written.
5. **Project tree**: still never scraped; briefs say findings-only deliverable
   (no “seed this file” operator recovery).
6. **Nano boundary unchanged**: no Autopilot tools; host owns parse/apply
   (IG-704).

---

## Work items

### A. Spec

- [x] RFC-231 §5.1 / §9 / decision log / routing → CE + rail_state SoT
- [x] This IG

### B. Runtime

- [x] `wave_plan.py`: delete artifact path helpers + dump/load
- [x] `RailJobState` / persist / load: drop `wave_plan_artifact`
- [x] `builtins_exec.record_wave_plan` / ingest / ready: apply-only
- [x] `interpreter.bind_job`: no artifact; still `ingest_wave_plan` from CE
- [x] Catalog: reject `fanout.artifact`
- [x] Rails YAML + `verb_defaults`: drop `artifact:`; simplify briefs
- [x] Service gate copy: findings-only

### C. Docs / skills (owned)

- [x] `docs/wiki/howto_debug.md` WavePlan stall recovery without file seed
- [x] `.agents/skills/inspect-autopilot-job/SKILL.md` forensics pointer

### D. Tests

- [x] Fan-out / gate tests assert rail_state / CE ready, not `.is_file()`
- [x] Catalog rejects `artifact`
- [x] Two-job isolation via `wave_slices` on state, not separate JSON files

### E. Out of scope (submodules)

- `soothe-nano` looprail-creator templates (`fanout.artifact`) — bump in nano
  repo separately; do not edit submodule from this monorepo.

---

## Non-goals

- Changing WavePlan JSON schema (`wave_slices` / `slices`)
- Softening `require_plan` architecture gate
- Scraping project-tree JSON back into CE

---

## Verification

`./scripts/verify_finally.sh` green after cleanse.

---

## Acceptance

1. Architecture accept with findings WavePlan → `wave_slices` on rail_state;
   **no** `wave-plan.json` created under `jobs_root`.
2. Presence of orphan `jobs/{id}/wave-plan.json` or project-tree plan files
   alone never makes `is_wave_plan_ready` true.
3. Catalog load fails if rail YAML still has `fanout.artifact`.
4. Operator recovery = re-run architecture with valid findings (or set
   `wave_slices` on `rail_state.json`), not `cat > wave-plan.json`.
