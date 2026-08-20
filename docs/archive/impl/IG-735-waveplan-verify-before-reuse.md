# IG-735: WavePlan verify-before-reuse (trivial StrangeLoop)

**Created**: 2026-08-09  
**Status**: Implemented  
**Package**: `soothe`  
**Related**: [IG-730](IG-730-waveplan-continue-short-circuit.md),
[IG-731](IG-731-autopilot-dispatch-intake-scope.md),
[RFC-630](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md),
[RFC-232](../specs/RFC-232-waveplan-flat-semistructured-ingest.md)

---

## Goal

Stop `plan_milestones` from auto-completing architecture and spawning makers
when a workspace/jobs WavePlan dump is present (IG-730 short-circuit). Stale
dumps from prior jobs (incident `88c0ba64` / dump from `a1b96ae5`) must be
**verified** by a StrangeLoop agent before fan-out.

## Design rules (MUST)

1. **No auto-accept** — host never completes architecture from a dump alone.
2. **Verify planner** — when a transfer dump makes `is_wave_plan_ready` and no
   prior architecture annotation exists, spawn a **pending** planner goal with
   a verify brief (source path + accept-or-rewrite instructions).
3. **Trivial StrangeLoop** — that verify goal sets per-goal
   `intake_scope="trivial"` so dispatch skips Pass 1+2 and runs a fresh
   1-step plan (no long rediscovery spine).
4. **Per-goal `intake_scope`** — `GoalNode.intake_scope` defaults to `null`;
   Autopilot dispatch prefers goal scope over `AutopilotConfig.intake_scope`.
5. **Retry unchanged** — prior architecture annotation → normal planner
   (`intake_scope=null`), not the verify short-path.
6. **Makers wait** — `spawn_wave_makers` still runs only after architecture
   completes and consensus/host ingest accepts a flat WavePlan.
7. **No IG/RFC ids** in user-visible briefs, logs, or errors.

## Work items

- [x] `GoalNode.intake_scope` (`trivial`|`simple`|`complex`|null)
- [x] `spawn_goal` recipe + L0 schema optional `intake_scope`
- [x] `_dispatch_to_worker` goal-over-config precedence
- [x] `_has_wave_plan_reuse_candidate` + `_plan_milestones_verify_existing`
- [x] `waveplan_verify_existing_brief` in verb_defaults
- [x] Unit: dump → pending trivial verify; no dump → null scope; retry ignores
      dump verify path; goal scope overrides config
- [x] Docs: IG-730 note + howto_debug continue section

## Non-goals

- Host-side light-LLM validity judge (agent + consensus remain SoT)
- Renaming wire `intake_scope` → `intent_scope`
- Healing already-dispatched jobs that auto-reused a dump

## Verification

- Unit: dump present → one pending planner, `intake_scope=trivial`, no makers
- Unit: empty workspace → normal pending planner, `intake_scope is None`
- Unit: `retry_architecture` after failed planner + dump → pending planner,
  not verify brief
- Unit: goal `intake_scope=trivial` overrides config `simple` on LoopRunRequest
