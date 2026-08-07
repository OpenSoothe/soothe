# IG-704: Autopilot host-owned wave-plan ingest (no nano tools)

**Created**: 2026-08-06  
**Status**: Implemented  
**Related**: [IG-720](IG-720-waveplan-ce-findings-no-file.md) (CE findings /
rail_state SoT; file artifact removed),
[IG-714](IG-714-architecture-wave-plan-accept-without-artifact.md)
(fail-closed accept without plan),
[RFC-232](../specs/RFC-232-waveplan-flat-semistructured-ingest.md)
(flat wire; nesting reject — follow-on),
[IG-700](../archive/impl/IG-700-greenfield-fanout-closeout.md),
[IG-699](../archive/impl/IG-699-llm-determined-rail-fanout-width.md),
RFC-222 (StrangeLoop never sees GoalEngine)

---

## Goal

Close greenfield fan-out so architecture goals can complete without teaching
nano / StrangeLoop about Autopilot plans or CE mutations.

## Boundary (MUST)

| Layer | Owns | Must not |
|-------|------|----------|
| Nano / StrangeLoop | Opaque goal text, normal tools, generic contribution | `record_wave_plan`, CE DAG, wave modules, jobs paths |
| Autopilot + LoopRail | Parse WavePlan from contribution, apply into `RailJobState`, gate accept, spawn makers | Inject Autopilot tools into CoreAgent; filesystem WavePlan JSON |

## Design

1. Architecture goal text asks for a **WavePlan JSON findings entry** only (no tool name).
2. On worker completion, AutopilotService parses candidates (evidence + findings)
   with structured JSON ingest (no markdown scrape).
3. On success → `RailBuiltinExecutor.record_wave_plan` (apply to rail_state) →
   deterministic **accept**.
4. On miss + `require_plan` → deterministic **send_back** (skip free-form consensus).
5. Agent-facing `wave_plan_tools.py` removed (no nano Autopilot wave-plan tools).
6. Rail: `architecture_failed` → `retry_architecture` (budgeted replant).

## Non-goals

- Nano Autopilot tools
- Workspace / project-tree / `jobs/*/wave-plan.json` files as source of truth
- Keyword/module-name heuristics (RFC-630)

## Follow-up

[IG-714](IG-714-architecture-wave-plan-accept-without-artifact.md) hardens the
gate so a missing / unbound rail interpreter cannot fall through to soft LLM
accept. [IG-720](IG-720-waveplan-ce-findings-no-file.md) removes the filesystem
WavePlan artifact entirely (CE findings + `rail_state` only).
