# IG-722: WavePlan multi-form transfer (SoT = job state)

**Created**: 2026-08-07  
**Status**: Implemented  
**Related**: [RFC-231](../specs/RFC-231-looprail-rail-exec.md) §9,
[RFC-232](../specs/RFC-232-waveplan-flat-semistructured-ingest.md),
[IG-720](IG-720-waveplan-ce-findings-no-file.md) (amended),
[IG-721](IG-721-waveplan-flat-semistructured-ingest.md)

---

## Goal

Keep **SoT** as `RailJobState.wave_slices` / `decompose_plan` (persisted in
`rail_state.json`), while allowing multiple **transfer** forms for a flat
WavePlan — including recommended dumps and a structured `wave_plan_path` for
custom files. Remove explicit bans that treated workspace / jobs JSON as
ignored orphans.

## Design rules (MUST)

1. **SoT**: applied `RailJobState` fields only. Optional
   `wave_plan_source_path` records which file supplied the plan.
2. **Transfer (any)**:
   - Structured `GoalDispatchContextContribution.wave_plan` /
     `wave_plan_path` (and matching `PlanResult` fields)
   - Recommended dumps: `$SOOTHE_DATA_DIR/jobs/{id}/wave-plan.json`,
     `<workspace>/.soothe/wave-plan.json`
   - Declarative allowlist under workspace
   - Completion findings / evidence JSON blob
3. Custom paths outside the allowlist require structured `wave_plan_path`
   (no prose path scraping).
4. Nested waves/slices still rejected (RFC-232).
5. Successful `record_wave_plan` mirrors both recommended dumps best-effort.
6. `fanout.artifact` YAML remains catalog-rejected.

## Work items

- [x] `wave_plan.py` multi-source diagnose + dump/path helpers + send_back copy
- [x] Contribution / PlanResult structured fields; runner pass-through
- [x] `RailJobState.wave_plan_source_path` persist/load
- [x] Service gate + builtins record/ingest/ready
- [x] Rail briefs, wiki, skill, RFC-231 §9
- [x] Tests for dumps / path / blob / escape reject

## Notes

Amends IG-720’s “files ignored / findings-only” rule. Flat schema (IG-721 /
RFC-232) unchanged.
