# IG-721: Flat WavePlan wire ingest (nesting reject + gate detail)

**Created**: 2026-08-07  
**Status**: Implemented  

**Related**: [RFC-232](../specs/RFC-232-waveplan-flat-semistructured-ingest.md),
[RFC-231](../specs/RFC-231-looprail-rail-exec.md) §9,
[IG-720](IG-720-waveplan-ce-findings-no-file.md),
[IG-704](IG-704-autopilot-wave-plan-host-ingest.md),
[IG-714](IG-714-architecture-wave-plan-accept-without-artifact.md)

---

## Goal

Implement RFC-232:

1. Detect and **reject** nested waves/slices (no clever-flatten).
2. Optional **flat-only** coerce (`slices[].name`→`slice`, scalar string fields).
3. Architecture gate `send_back` includes validation/nesting **detail**.
4. Planner briefs / wiki / skill: flat contract, nesting forbidden.

SoT: `RailJobState.wave_slices` (transfer via multi-form ingest — IG-722).

---

## Work items

- [x] `wave_plan.py`: `WavePlanIngestResult`, nesting guards, flat coerce, diagnose APIs
- [x] `AutopilotService` architecture gate: detailed send_back
- [x] `verb_defaults` + greenfield/migration `plan_milestones` briefs
- [x] Unit tests (parse + gate)
- [x] `howto_debug.md` + inspect-autopilot-job skill note
- [x] `./scripts/verify_finally.sh` green (use `UV_PYPI_MIRROR` when PyPI resets)
- [x] Post-impl cleanse: drop unused `WavePlanIngestResult.ok`, redundant
  post-coerce nesting pass, dead send_back startswith branch; gate test asserts
  guidance; stale “bare WavePlan” wording in runner/skill/IG-714

---

## Non-goals

- Dedicated `PlanResult.wave_plan` field (RFC-232 open Q)
- Operator CLI `wave-plan set`
- Restoring filesystem SoT
