# IG-712: Domain-independent goal effects (replace `files_touched`)

**Created**: 2026-08-06  
**Status**: Done  
**Related**: [RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md),
[RFC-230](../specs/RFC-230-job-maturity-assessment.md),
[RFC-204](../specs/RFC-204-autopilot-mode.md),
[IG-710](IG-710-consensus-trust-sloop-response.md),
[IG-711](IG-711-llm-job-maturity.md)

---

## Goal

Replace host regex/disk `files_touched` heuristics with StrangeLoop-emitted
structured `GoalEffect` claims that work for any workspace domain (coding,
research, ops, narrative-only, APIs). Effects are hydration + observability
metadata only — never a consensus or maturity latch.

## Design rules

1. StrangeLoop assess (when `status=done`) emits `effects: list[GoalEffect]`
   via structured output (RFC-630 — no host keyword inference from prose).
2. Worker copies `PlanResult.effects` into `GoalDispatchContextContribution.effects`
   (passthrough).
3. `ContextProjector` merges by `ref` (latest parent wins), capped by
   `context_projection.max_effects`.
4. Child dispatch hydrates a capped **Prior effects** section alongside
   operator guidance.
5. Consensus remains goal text + sloop response (IG-710). Maturity remains
   LLM contract judgment (IG-711). Effects never latch accept.

## Schema

```text
GoalEffect:
  kind: produce | mutate | observe | communicate | decide
  ref: opaque handle (path, URL, ticket id, "answer", …)
  statement: one-line claim
  digest: optional version/hash
  confidence: 0..1
  goal_id_origin: set by projector on prior_effects
```

## Deliverables

- [x] IG + RFC-222 / RFC-230 notes
- [x] Remove `build_files_touched` / path-token regex
- [x] `GoalEffect` on contribution/bundle; projector `_merge_effects`; `max_effects`
- [x] StatusAssessment / PlanResult effects; worker passthrough
- [x] Child hydration of prior effects

## Non-goals

- Host filesystem probes as accept criteria
- Inferring effects from evidence prose
- Effects as consensus / maturity latch
- Per-path workspace locking
