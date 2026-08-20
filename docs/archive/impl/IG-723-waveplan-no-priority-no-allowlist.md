# IG-723: Remove WavePlan priority and path allowlist

**Created**: 2026-08-07  
**Status**: Implemented  
**Related**: [RFC-232](../specs/RFC-232-waveplan-flat-semistructured-ingest.md),
[IG-722](IG-722-waveplan-multiform-transfer.md)

---

## Goal

Stop rejecting agent WavePlan dumps for wire `priority` (e.g. `"P0"`), and
remove the declarative workspace path allowlist. Keep transfer explicit;
suggested dump paths remain optional convenience reads and brief suggestions.

## Design rules (MUST)

1. `WavePlanSlice` has no `priority`; extra wire keys are ignored.
2. `as_decompose_plan` / spawn order follows slice list order; maker goal
   priority uses the host default when the spec has no priority.
3. No `WAVE_PLAN_WORKSPACE_ALLOWLIST`; ingest order is inline →
   `wave_plan_path` → jobs dump → `.soothe` dump → findings.
4. Briefs / send-back suggest dump paths; do not require allowlist or force
   a single save location.
5. Escape outside workspace/jobs roots still rejected.
6. Prefer schema/path ingest details over findings `not a JSON object` noise.

## Work items

- [x] Remove priority from WavePlan model + sort-by-priority spawn
- [x] Remove allowlist; update prompts / send-back / Field docs
- [x] Fix `_prefer_ingest_detail`
- [x] Unit tests + howto_debug
